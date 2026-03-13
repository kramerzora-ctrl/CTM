import numpy as np

# ==========================================
# CTM Configuration & State Structures
# ==========================================

class EdgeConfig:
    """Holds the static physical configuration of an edge."""
    def __init__(self, edge_id, config, dt_sec):
        self.edge_id = edge_id
        self.source = config['source']
        self.target = config['target']
        self.length = config['length']
        self.lanes = config['lanes']
        self.v = config['v']
        
        # Read merge_weight, default to 1 for backwards compatibility
        self.merge_weight = config.get('merge_weight', 1.0)
        
        # Convert capacities and parameters to vehicles per time step (dt)
        self.q_max = config['q_max'] * self.lanes * (dt_sec / 3600.0)
        
        # Determine number of cells (L_cell approx equals v * dt)
        ideal_cell_length = self.v * (dt_sec / 3600.0)
        self.num_cells = max(1, round(self.length / ideal_cell_length))
        self.cell_length = self.length / self.num_cells
        
        # Max vehicles the cell can hold physically based on the DISCRETIZED length
        self.n_max = config['k_jam'] * self.lanes * self.cell_length
        self.v_eff_mph = self.cell_length / (dt_sec / 3600.0)
        
        # Recalculate the w/v ratio perfectly for the discretized cell.
        # This guarantees that when n = q_max, Receiving capacity (R) perfectly equals q_max, 
        # completely eliminating artificial discretization bottlenecks.
        available_space_at_capacity = max(1e-9, self.n_max - self.q_max)
        self.w_v_ratio = self.q_max / available_space_at_capacity
        
        # Calculate resulting dynamic w for reference
        self.w = self.w_v_ratio * self.v_eff_mph

class EdgeState:
    """Holds the dynamic multi-commodity state matrices for an edge."""
    def __init__(self, num_steps, num_cells, num_destinations):
        # n[t, i, k] = number of vehicles in cell i at time t bound for destination k
        self.n = np.zeros((num_steps + 1, num_cells, num_destinations))
        
        # y[t, i, k] = flow INTO cell i at time t bound for destination k. 
        # Size is num_cells + 1 so y[t, -1, k] represents flow OUT of the last cell.
        self.y = np.zeros((num_steps, num_cells + 1, num_destinations))

class NodeState:
    """Holds the dynamic multi-commodity state vectors for nodes (e.g. source queues, meters)."""
    def __init__(self, num_steps, num_destinations):
        # queue[t, k] = number of vehicles waiting at the source node at time t bound for destination k
        self.queue = np.zeros((num_steps + 1, num_destinations))
        
        # meter_rate[t] = maximum allowed flow through this node at time t. 
        # Initialized to infinity so normal nodes are unrestricted.
        self.meter_rate = np.full(num_steps, np.inf)