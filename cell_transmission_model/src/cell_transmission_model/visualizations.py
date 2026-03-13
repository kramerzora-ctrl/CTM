import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict

def plot_results(network, segments_sequence=None):
    """Generates the Space-Time Diagram and Queue profiles directly from the network."""
    print("\n--- Collecting Statistics and Post-Processing ---")
    
    # Use provided sequence if valid
    if segments_sequence:
        segments_sequence = [eid for eid in segments_sequence if eid in network.edges_config]
    
    # Fallback to all available edges if specific ones aren't provided or found
    if not segments_sequence:
        segments_sequence = list(network.edges_config.keys())
        
    history = {
        'mainline_density': [],
        'queue_lengths': defaultdict(list),
        'time': [step * network.dt for step in range(network.num_steps)]
    }
    
    # Collect queue lengths (Summed over destinations for overall tracking)
    for nid in network.nodes_config.keys():
        total_queue = np.sum(network.nodes_state[nid].queue[:-1, :], axis=1)
        history['queue_lengths'][nid] = total_queue.tolist()
        
    # Collect mainline densities and determine dynamic max k_jam
    edge_densities = []
    max_k_jam = 200 # Default fallback
    
    for eid in segments_sequence:
        edge_config = network.edges_config[eid]
        state = network.edges_state[eid]
        
        # Extract k_jam dynamically from the network configuration
        # n_max = k_jam * lanes * cell_length => k_jam = n_max / (lanes * cell_length)
        k_jam = edge_config.n_max / (edge_config.lanes * edge_config.cell_length)
        if k_jam > max_k_jam or max_k_jam == 200:
            max_k_jam = k_jam
        
        # Sum over destination axis (axis=2) to get total density
        total_n = np.sum(state.n[:-1, :, :], axis=2)
        density = total_n / (edge_config.cell_length * edge_config.lanes)
        edge_densities.append(density)
        
    # Concatenate along the spatial axis (axis=1) and convert to list of lists
    if edge_densities:
        history['mainline_density'] = np.hstack(edge_densities).tolist()
        
    print("\nGenerating simulation plots...")
    
    # Space-Time Diagram
    density_matrix = np.array(history['mainline_density'])
    
    # Use gridspec to properly align axes when adding a colorbar
    # Column 0 holds the plots, Column 1 holds the colorbar.
    # layout='constrained' handles the complex GridSpec spacing natively without warnings.
    fig = plt.figure(figsize=(12, 10), layout='constrained')
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 0.03])
    
    ax1 = fig.add_subplot(gs[0, 0])
    cax = fig.add_subplot(gs[0, 1])
    
    # 1. Plot Space-Time density
    im = ax1.imshow(density_matrix.T, aspect='auto', origin='lower', cmap='Reds', 
                    vmin=0, vmax=max_k_jam,
                    extent=[0, max(history['time']), 0, density_matrix.shape[1] if len(density_matrix.shape) > 1 else 0])
    
    title_text = 'Space-Time Density Diagram'
    if segments_sequence:
        title_text += f'\n({", ".join(segments_sequence)})'
    
    ax1.set_title(title_text)
    # The x-axis label is removed here because it is shared with ax2
    ax1.set_ylabel('Space (Cell Index -> flow direction)')
    
    # Plot colorbar into its dedicated grid axis
    cbar = fig.colorbar(im, cax=cax)
    cbar.set_label('Density (veh/mile/lane)')
    
    
    plt.savefig('ctm_spacetime_results.png', dpi=300)
    print("Plots saved as 'ctm_spacetime_results.png'.")
    plt.show()