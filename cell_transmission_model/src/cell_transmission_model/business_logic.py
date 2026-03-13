import numpy as np

# ==========================================
# CTM Business Logic (Strict FIFO Diverges via Tracker)
# ==========================================

# In-memory tracker for diverge cells to maintain FIFO tau distribution
# Maps edge_id -> np.ndarray of shape (num_dests, max_tau)
_diverge_trackers = {}

def resolve_fifo_boundary(n_dest_tau, max_S, R_dict, dest_to_out=None):
    """
    Evaluates the FIFO queue layer by layer (from oldest tau to newest)
    to find the exact threshold fraction where the flow hits a capacity limit.
    """
    num_dests, max_tau = n_dest_tau.shape
    y_out = np.zeros_like(n_dest_tau)
    
    S_avail = max_S
    R_avail = {k: v for k, v in R_dict.items()}
    
    # Iterate from oldest vehicles (max_tau - 1) down to newest (0)
    for tau in range(max_tau - 1, -1, -1):
        group_demand = n_dest_tau[:, tau]
        total_group = np.sum(group_demand)
        
        if total_group == 0:
            continue
            
        # Calculate allowed fraction based on upstream Sending capacity
        f_S = S_avail / total_group if total_group > 0 else 1.0
        
        # Calculate allowed fraction based on downstream Receiving capacities
        f_R = 1.0
        if dest_to_out is not None:
            out_demand = {}
            for d in range(num_dests):
                out_id = dest_to_out.get(d)
                if out_id is not None:
                    out_demand[out_id] = out_demand.get(out_id, 0.0) + group_demand[d]
            
            for out_id, req in out_demand.items():
                if req > 0:
                    f_R = min(f_R, R_avail[out_id] / req)
        
        # The limiting fraction is the minimum constraint (Alpha threshold logic)
        f = min(1.0, f_S, f_R)
        
        # Apply fraction to the group
        y_out[:, tau] = group_demand * f
        
        # Deduct used capacity for the next tau iteration
        S_avail -= np.sum(y_out[:, tau])
        if dest_to_out is not None:
            for d in range(num_dests):
                out_id = dest_to_out.get(d)
                if out_id is not None:
                    R_avail[out_id] -= y_out[d, tau]
                    
        # If we hit a bottleneck (f < 1.0), FIFO dictates no younger vehicles can move
        if f < 1.0:
            break
            
    return y_out

def compute_transfers(n_matrices, q_matrices, m_matrices, y_matrices, edges_config, nodes_config, routing_table, step):
    """
    Computes the receiving flows/transfers (y) using 3D matrices, but applies 
    strict Multi-Commodity FIFO CTM physics dynamically at diverges using the tracker.
    """
    if step == 0:
        _diverge_trackers.clear()
        
    S = {}
    R = {}
    P = {}

    # 1. Precompute Sending (S), Receiving (R), and Proportions (P)
    for eid, config in edges_config.items():
        n_current = n_matrices[eid][step, :, :]
        n_total = np.sum(n_current, axis=1)
        
        S[eid] = np.minimum(n_total, config.q_max)
        available_space = np.maximum(0.0, config.n_max - n_total)
        R[eid] = np.minimum(config.q_max, available_space * config.w_v_ratio)
        
        p = np.zeros_like(n_current)
        mask = n_total > 0
        p[mask] = n_current[mask] / n_total[mask, None]
        P[eid] = p

    # 2. Compute internal transfers
    for eid, config in edges_config.items():
        num_cells = config.num_cells
        y_matrices[eid][step, :, :] = 0.0
        
        if num_cells > 1:
            internal_y_total = np.minimum(S[eid][:-1], R[eid][1:])
            y_matrices[eid][step, 1:-1, :] = internal_y_total[:, None] * P[eid][:-1, :]

    # 3. Compute Node Boundary Transfers
    incoming = {nid: [] for nid in nodes_config}
    outgoing = {nid: [] for nid in nodes_config}
    for eid, config in edges_config.items():
        outgoing[config.source].append(eid)
        incoming[config.target].append(eid)

    for nid, node in nodes_config.items():
        ntype = node['type']
        ins = incoming[nid]
        outs = outgoing[nid]

        if ntype == 'source':
            if outs:
                out_eid = outs[0]
                q_current = q_matrices[nid][step, :]
                q_total = np.sum(q_current)
                R_down = R[out_eid][0]
                
                if q_total > 0:
                    # Added 1e-9 tolerance to safely bypass float smear when uncongested
                    if q_total <= R_down + 1e-9:
                        y_matrices[out_eid][step, 0, :] = q_current.copy()
                    else:
                        p_q = q_current / q_total
                        y_total = min(q_total, R_down)
                        y_matrices[out_eid][step, 0, :] = y_total * p_q

        elif ntype == 'sink':
            if ins:
                in_eid = ins[0]
                y_matrices[in_eid][step, -1, :] = S[in_eid][-1] * P[in_eid][-1, :]

        elif ntype == 'diverge':
            if len(ins) == 1 and len(outs) > 0:
                in_eid = ins[0]
                n_current = n_matrices[in_eid][step, -1, :]
                num_dests = n_current.shape[0]
                
                # Init tracker for this diverge cell if missing
                if in_eid not in _diverge_trackers:
                    _diverge_trackers[in_eid] = n_current[:, None].copy()
                    
                tau_state = _diverge_trackers[in_eid]
                
                # Synchronize tracker with actual n_current to prevent float drift
                total_tau = np.sum(tau_state, axis=1)
                mask = total_tau > 0
                if np.any(mask):
                    tau_state[mask] = tau_state[mask] * (n_current[mask] / total_tau[mask])[:, None]
                mask_zero = (total_tau == 0) & (n_current > 0)
                if np.any(mask_zero):
                    tau_state[mask_zero, 0] = n_current[mask_zero]
                
                # Evaluate diverge using the FIFO memory
                S_limit = S[in_eid][-1]
                R_dict = {out_eid: R[out_eid][0] for out_eid in outs}
                dest_to_out = routing_table.get(nid, {})
                
                y_out_tau = resolve_fifo_boundary(tau_state, S_limit, R_dict, dest_to_out)
                y_total_out = np.sum(y_out_tau, axis=1)
                
                y_matrices[in_eid][step, -1, :] = y_total_out
                
                for dest_idx, out_eid in dest_to_out.items():
                    if out_eid in outs:
                        y_matrices[out_eid][step, 0, dest_idx] = y_total_out[dest_idx]
                        
                # Temporarily save the remaining vehicles to be shifted in update_states
                _diverge_trackers[in_eid] = np.maximum(0.0, tau_state - y_out_tau)

        elif ntype == 'merge':
            if len(outs) == 1 and len(ins) == 2:
                out_eid = outs[0]
                in1, in2 = ins[0], ins[1]
                R_down = R[out_eid][0]
                S1, S2 = S[in1][-1], S[in2][-1]

                w1 = getattr(edges_config[in1], 'merge_weight', 1.0)
                w2 = getattr(edges_config[in2], 'merge_weight', 1.0)
                total_w = w1 + w2
                p1 = w1 / total_w if total_w > 0 else 0.5
                p2 = w2 / total_w if total_w > 0 else 0.5

                if S1 + S2 <= R_down:
                    y1_total, y2_total = S1, S2
                else:
                    y1_total = np.median([S1, R_down - S2, p1 * R_down])
                    y2_total = np.median([S2, R_down - S1, p2 * R_down])

                y_matrices[in1][step, -1, :] = y1_total * P[in1][-1, :]
                y_matrices[in2][step, -1, :] = y2_total * P[in2][-1, :]
                y_matrices[out_eid][step, 0, :] = y_matrices[in1][step, -1, :] + y_matrices[in2][step, -1, :]

        elif ntype == 'meter':
            if len(ins) == 1 and len(outs) == 1:
                in_eid, out_eid = ins[0], outs[0]
                meter_capacity = m_matrices[nid][step]
                y_total = min(S[in_eid][-1], R[out_eid][0], meter_capacity)
                transfer_vector = y_total * P[in_eid][-1, :]
                y_matrices[in_eid][step, -1, :] = transfer_vector
                y_matrices[out_eid][step, 0, :] = transfer_vector

        else:
            if len(ins) == 1 and len(outs) == 1:
                in_eid, out_eid = ins[0], outs[0]
                y_total = min(S[in_eid][-1], R[out_eid][0])
                transfer_vector = y_total * P[in_eid][-1, :]
                y_matrices[in_eid][step, -1, :] = transfer_vector
                y_matrices[out_eid][step, 0, :] = transfer_vector

    return y_matrices


def update_states(n_matrices, y_matrices, step):
    """
    Pure function to compute the accumulation (n) for the next time step.
    Additionally updates the FIFO memory trackers for diverge boundaries.
    """
    for eid, n_array in n_matrices.items():
        y_array = y_matrices[eid]
        
        n_old = n_array[step, :, :]
        y_in = y_array[step, :-1, :]
        y_out = y_array[step, 1:, :]
        
        new_n = n_old + y_in - y_out
        
        # Clean up floating-point dust from matrices
        new_n[new_n < 1e-9] = 0.0
        n_matrices[eid][step + 1, :, :] = new_n
        
        # --- Update Diverge Tracker Memory ---
        if eid in _diverge_trackers:
            staying_tau = _diverge_trackers[eid] 
            new_arrivals = y_in[-1, :] # New arrivals entering the final cell of this edge
            
            # Prepend new arrivals (tau=0), shifting the staying vehicles older (tau+1)
            new_tau_state = np.column_stack([new_arrivals, staying_tau])
            
            # Prune trailing empty tau columns to save memory footprint
            while new_tau_state.shape[1] > 1 and np.sum(new_tau_state[:, -1]) < 1e-9:
                new_tau_state = new_tau_state[:, :-1]
                
            # Clean up tracker dust
            new_tau_state[new_tau_state < 1e-9] = 0.0
            _diverge_trackers[eid] = new_tau_state
                
    return n_matrices


def update_node_queues(q_matrices, y_matrices, edges_config, nodes_config, demand_profile, step):
    """
    Function for queue updates pure functionally. 
    Subtracts entered vehicles and adds new demand from the OD matrix.
    """
    outgoing = {nid: [] for nid in nodes_config}
    for eid, config in edges_config.items():
        outgoing[config.source].append(eid)
        
    for nid, q_array in q_matrices.items():
        new_q = q_array[step, :]
        
        if nodes_config[nid]['type'] == 'source':
            outs = outgoing[nid]
            if outs:
                out_eid = outs[0]
                flow_out = y_matrices[out_eid][step, 0, :]
                new_q = new_q - flow_out
                
        if nid in demand_profile:
            new_q = new_q + demand_profile[nid][step, :]
        
        # Clean up floating-point dust from source queues
        new_q[new_q < 1e-9] = 0.0
        q_matrices[nid][step + 1, :] = new_q
        
    return q_matrices