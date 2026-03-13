import yaml
import numpy as np
import os
import pandas as pd
from collections import defaultdict, deque
from tqdm import tqdm

from .structures import EdgeConfig, EdgeState, NodeState
from .business_logic import compute_transfers, update_states, update_node_queues
from .visualizations import plot_results

# ==========================================
# Utilities
# ==========================================

def validate_flows(edges_state, num_steps):
    """
    Checks the integrity of the results by validating that the mass conservation 
    equation holds true across all cells and time steps.
    """
    print("\n--- Validating Flow Integrity ---")
    all_valid = True
    for eid, state in edges_state.items():
        for t in range(num_steps):
            expected_n = state.n[t, :, :] + state.y[t, :-1, :] - state.y[t, 1:, :]
            
            # Use np.allclose to account for minor floating point inaccuracies
            if not np.allclose(state.n[t + 1, :, :], expected_n, atol=1e-8):
                print(f"  Integrity Error at Edge '{eid}', Time Step {t}")
                all_valid = False
                
    if all_valid:
        print("  Success! All flows validated. n_{t+1} = n_t + y_in - y_out holds true.")
    else:
        print("  Warning: Flow integrity validation failed.")

def export_to_excel(edges_state, filename="ctm_results.xlsx", disaggregated=False):
    """
    Saves the 'n' and 'y' matrices to an Excel file.
    If disaggregated is True, it exports individual sheets for each destination.
    """
    print(f"\n--- Exporting matrices to {filename} ---")
    try:
        with pd.ExcelWriter(filename) as writer:
            for eid, state in edges_state.items():
                num_dests = state.n.shape[2]
                
                if disaggregated:
                    # Excel sheet names have a 31 character limit
                    # Reserve space for _n_DXX suffix
                    safe_eid = eid[:21] 
                    
                    for d in range(num_dests):
                        # Export Accumulation (n) for destination d
                        df_n = pd.DataFrame(state.n[:, :, d], columns=[f"Cell_{i}" for i in range(state.n.shape[1])])
                        df_n.index.name = "Time_Step"
                        df_n.to_excel(writer, sheet_name=f"{safe_eid}_n_D{d}")
                        
                        # Export Flows (y) for destination d
                        df_y = pd.DataFrame(state.y[:, :, d], columns=[f"Flow_In_{i}" for i in range(state.y.shape[1]-1)] + ["Flow_Out_Last"])
                        df_y.index.name = "Time_Step"
                        df_y.to_excel(writer, sheet_name=f"{safe_eid}_y_D{d}")
                else:
                    # Excel sheet names have a 31 character limit
                    safe_eid = eid[:25] 
                    
                    # Export Accumulation (n) - Summing over destinations temporarily
                    total_n = np.sum(state.n, axis=2)
                    df_n = pd.DataFrame(total_n, columns=[f"Cell_{i}" for i in range(total_n.shape[1])])
                    df_n.index.name = "Time_Step"
                    df_n.to_excel(writer, sheet_name=f"{safe_eid}_n")
                    
                    # Export Flows (y) - Summing over destinations temporarily
                    total_y = np.sum(state.y, axis=2)
                    df_y = pd.DataFrame(total_y, columns=[f"Flow_In_{i}" for i in range(total_y.shape[1]-1)] + ["Flow_Out_Last"])
                    df_y.index.name = "Time_Step"
                    df_y.to_excel(writer, sheet_name=f"{safe_eid}_y")
                    
        print("  Export complete.")
    except Exception as e:
        print(f"  Failed to export to Excel: {e}")


# ==========================================
# Network Manager
# ==========================================

class CTMNetwork:
    def __init__(self, config_path):
        print(f"Loading network configuration from {config_path}...")
        with open(config_path, 'r') as file:
            self.config = yaml.safe_load(file)
            
        self.dt = self.config['simulation']['time_step']
        self.total_time = self.config['simulation']['total_time']
        self.num_steps = int(self.total_time / self.dt)
        
        self.nodes_config = {}
        self.edges_config = {}
        
        # Setup Multi-Commodity Destinations
        self.destinations = [n['id'] for n in self.config['nodes'] if n['type'] == 'sink']
        self.num_destinations = len(self.destinations)
        self.dest_to_index = {dest: i for i, dest in enumerate(self.destinations)}
        
        # State Data
        self.edges_state = {}
        self.nodes_state = {}
        
        self._build_routing_table()
        self._build_network()
        self._route_demand()

    def _build_routing_table(self):
        """Builds a backward-BFS routing table mapping each node to the next edge for a given destination."""
        # routing_table[node_id][dest_index] = edge_id_to_take
        self.routing_table = defaultdict(dict)
        
        for dest_idx, dest_id in enumerate(self.destinations):
            queue = deque([dest_id])
            visited = {dest_id}
            
            while queue:
                current_node = queue.popleft()
                # Find all edges arriving AT current_node
                incoming_edges = [e for e in self.config['edges'] if e['target'] == current_node]
                
                for edge in incoming_edges:
                    prev_node = edge['source']
                    # The route FROM prev_node TO dest_id is via this edge
                    self.routing_table[prev_node][dest_idx] = edge['id']
                    
                    if prev_node not in visited:
                        visited.add(prev_node)
                        queue.append(prev_node)

    def _build_network(self):
        # 1. Initialize Nodes configuration & state
        for n_conf in self.config['nodes']:
            nid = n_conf['id']
            self.nodes_config[nid] = n_conf
            self.nodes_state[nid] = NodeState(self.num_steps, self.num_destinations)
            
        # 2. Initialize Edges configuration & state matrices
        print("\n--- Initializing Discretized Edges ---")
        for e_conf in self.config['edges']:
            eid = e_conf['id']
            config = EdgeConfig(eid, e_conf, self.dt)
            self.edges_config[eid] = config
            
            # Initialize 3D n and y matrices for this edge
            self.edges_state[eid] = EdgeState(self.num_steps, config.num_cells, self.num_destinations)
            
            print(f"Edge '{eid}': Length={config.length}mi, created {config.num_cells} cells of length {config.cell_length:.4f}mi")
            
    def _route_demand(self):
        """Map OD matrix configuration (Logic separated from State)"""
        print("\n--- Processing Time-Dependent Demand & Routing ---")
        
        # Parse the time-dependent OD demand into a usable array structure for the source queues
        self.demand_profile = defaultdict(lambda: np.zeros((self.num_steps, self.num_destinations)))
        
        if 'od_demand' in self.config:
            for demand in self.config['od_demand']:
                origin = demand['origin']
                destination = demand['destination']
                start_time = demand['start_time']
                end_time = demand['end_time']
                rate_vph = demand['rate']
                
                if destination not in self.dest_to_index:
                    continue
                    
                dest_idx = self.dest_to_index[destination]
                
                # Convert rate (veh/hr) to veh/step
                veh_per_step = rate_vph * (self.dt / 3600.0)
                
                # Convert times to step indices
                start_step = int(start_time / self.dt)
                end_step = min(self.num_steps, int(end_time / self.dt))
                
                # Assign to demand profile matrix
                if start_step < self.num_steps:
                    self.demand_profile[origin][start_step:end_step, dest_idx] += veh_per_step
                    
        # Parse Metering Schedules
        if 'meter_schedule' in self.config:
            for schedule in self.config['meter_schedule']:
                node_id = schedule['node']
                start_time = schedule['start_time']
                end_time = schedule['end_time']
                rate_vph = schedule['rate']
                
                if node_id in self.nodes_state:
                    # Convert rate (veh/hr) to veh/step
                    veh_per_step = rate_vph * (self.dt / 3600.0)
                    start_step = int(start_time / self.dt)
                    end_step = min(self.num_steps, int(end_time / self.dt))
                    
                    if start_step < self.num_steps:
                        self.nodes_state[node_id].meter_rate[start_step:end_step] = veh_per_step
                    print(f"Meter Node '{node_id}' schedule configured: {rate_vph} vph from {start_time}s to {end_time}s.")
        
        for n_conf in self.config['nodes']:
            if n_conf['type'] == 'diverge':
                print(f"Diverge Node '{n_conf['id']}' dynamic profiles configured.")
            elif n_conf['type'] == 'merge':
                # Dummy priorities for print
                priorities = "Placeholder priorities based on capacity"
                print(f"Merge Node '{n_conf['id']}' Priorities configured: {priorities}")

    def run(self):
        print(f"\n--- Starting CTM Simulation ({self.num_steps} steps) ---")
        
        # Extract entire sets of matrices into dictionaries
        n_matrices = {eid: state.n for eid, state in self.edges_state.items()}
        y_matrices = {eid: state.y for eid, state in self.edges_state.items()}
        q_matrices = {nid: state.queue for nid, state in self.nodes_state.items()}
        m_matrices = {nid: state.meter_rate for nid, state in self.nodes_state.items()}
        
        for step in tqdm(range(self.num_steps), desc="Simulating"):
            
            # --------------------------------------------------
            # STATELESS BUSINESS LOGIC EXECUTION
            # --------------------------------------------------
            
            # 1. Compute the transfers (y) for all segments and nodes
            y_matrices = compute_transfers(
                n_matrices, q_matrices, m_matrices, y_matrices, 
                self.edges_config, self.nodes_config, self.routing_table, step
            )
            
            # 2. Update the states (n and queues) for all segments and auxiliary nodes
            n_matrices = update_states(
                n_matrices, y_matrices, step
            )
            q_matrices = update_node_queues(
                q_matrices, y_matrices, self.edges_config, self.nodes_config, self.demand_profile, step
            )
            
            # --------------------------------------------------
            
        # Apply final computed matrices back to the state objects
        for eid in self.edges_state:
            self.edges_state[eid].n = n_matrices[eid]
            self.edges_state[eid].y = y_matrices[eid]
        for nid in self.nodes_state:
            self.nodes_state[nid].queue = q_matrices[nid]
            
        print("--- Simulation Complete ---")

# If running directly
if __name__ == "__main__":
    if os.path.exists("network_config.yaml"):
        net = CTMNetwork("network_config.yaml")
        net.run()
        
        # Define specific edges for the space-time diagram
        mainline_edges = ['mainline_seg1', 'mainline_seg2', 'mainline_seg3', 'on_ramp']
        plot_results(net, mainline_sequence=mainline_edges)
    else:
        print("Please ensure network_config.yaml is in the same directory.")