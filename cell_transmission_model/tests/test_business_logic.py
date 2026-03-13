import unittest
import numpy as np

# Importing the logic functions extracted previously
from cell_transmission_model.business_logic import compute_transfers, update_states, update_node_queues

class MockEdgeConfig:
    """A lightweight mock configuration to test the physics functions."""
    def __init__(self, q_max=10.0, n_max=50.0, w_v_ratio=1.0, num_cells=2, source='node1', target='node2'):
        self.q_max = q_max
        self.n_max = n_max
        self.w_v_ratio = w_v_ratio
        self.num_cells = num_cells
        self.source = source
        self.target = target

class TestBusinessLogic(unittest.TestCase):
    def setUp(self):
        """
        Set up a generic environment before each test runs.
        We simulate a small 2-cell configuration over 2 time steps, with 2 destinations.
        """
        self.step = 0
        self.num_steps = 2
        self.num_cells = 2
        self.num_dest = 2
        
        # Initialize generic 3D state matrices
        self.n_matrices = {'edge1': np.zeros((self.num_steps + 1, self.num_cells, self.num_dest))}
        self.y_matrices = {'edge1': np.zeros((self.num_steps, self.num_cells + 1, self.num_dest))}
        self.q_matrices = {'node1': np.zeros((self.num_steps + 1, self.num_dest))}
        self.m_matrices = {
            'node1': np.full(self.num_steps, np.inf),
            'node2': np.full(self.num_steps, np.inf)
        }
        
        # Setup mocked configs required for physics calculations
        self.edges_config = {'edge1': MockEdgeConfig()}
        self.nodes_config = {
            'node1': {'type': 'source', 'id': 'node1'},
            'node2': {'type': 'sink', 'id': 'node2'}
        }
        self.routing_table = {}
        self.demand_profile = {}

    def test_compute_transfers_internal_flow(self):
        """
        Test that compute_transfers correctly bounds flow by Sending (S) and Receiving (R) capacities
        summed across destinations.
        """
        # Set cell 0 to have 5 vehicles (dest 0). Set cell 1 to have 45 vehicles (dest 1).
        self.n_matrices['edge1'][self.step, 0, 0] = 5.0 
        self.n_matrices['edge1'][self.step, 1, 1] = 45.0 
        
        y_res = compute_transfers(
            self.n_matrices, self.q_matrices, self.m_matrices, self.y_matrices, 
            self.edges_config, self.nodes_config, self.routing_table, self.step
        )
        
        # cell 0 S = min(5, 10) = 5
        # cell 1 R = min(10, (50-45)*1.0) = 5
        # So flow from cell 0 to cell 1 = min(5, 5) = 5.0 for destination 0
        self.assertEqual(y_res['edge1'][self.step, 1, 0], 5.0)

    def test_update_states_multi_commodity(self):
        """
        Test that accumulation (n) properly updates on the 3rd axis for multi-commodity matrices.
        """
        # Set up state: Cell 0 has 10 of dest 0. Cell 1 has 20 of dest 1.
        self.n_matrices['edge1'][self.step, 0, 0] = 10.0
        self.n_matrices['edge1'][self.step, 1, 1] = 20.0
        
        # Flow IN cell 0 = 5.0 (dest 0)
        self.y_matrices['edge1'][self.step, 0, 0] = 5.0 
        
        # Flow FROM cell 0 to cell 1 = 2.0 (dest 0)
        self.y_matrices['edge1'][self.step, 1, 0] = 2.0 
        
        # Flow OUT cell 1 = 4.0 (dest 1)
        self.y_matrices['edge1'][self.step, 2, 1] = 4.0 
        
        n_res = update_states(self.n_matrices, self.y_matrices, self.step)
        
        # Cell 0 Dest 0 expected: 10 + 5 - 2 = 13
        self.assertEqual(n_res['edge1'][self.step + 1, 0, 0], 13.0)
        
        # Cell 1 Dest 0 expected: 0 + 2 - 0 = 2 (The transfer just arrived)
        self.assertEqual(n_res['edge1'][self.step + 1, 1, 0], 2.0)
        
        # Cell 1 Dest 1 expected: 20 + 0 - 4 = 16
        self.assertEqual(n_res['edge1'][self.step + 1, 1, 1], 16.0)

    def test_update_node_queues(self):
        """
        Test that the queue correctly subtracts entered vehicles and adds dynamic demand profile
        on a per-destination basis.
        """
        # Set up a starting queue of 15 vehicles for dest 0
        self.q_matrices['node1'][self.step, 0] = 15.0
        
        # Simulate 5 vehicles successfully transferring from source into the edge (dest 0)
        self.y_matrices['edge1'][self.step, 0, 0] = 5.0
        
        # Add a demand profile of 8 new vehicles arriving for dest 0 during this step
        self.demand_profile['node1'] = np.zeros((self.num_steps, self.num_dest))
        self.demand_profile['node1'][self.step, 0] = 8.0
        
        q_res = update_node_queues(
            self.q_matrices, self.y_matrices, 
            self.edges_config, self.nodes_config, self.demand_profile, self.step
        )
        
        # Dest 0: 15 queue - 5 left + 8 arrived = 18 remain
        self.assertEqual(q_res['node1'][self.step + 1, 0], 18.0)


if __name__ == '__main__':
    unittest.main()