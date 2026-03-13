import unittest
import yaml
import os
import copy
import numpy as np

from cell_transmission_model import CTMNetwork

class TestIntegrationMergeFlow(unittest.TestCase):
    def setUp(self):
        """
        Create a base custom network_config.yaml dictionary with a merge topology.
        Two upstream links merging into one bottleneck downstream link.
        """
        self.test_config_path = "temp_merge_config.yaml"
        self.base_config = {
            "simulation": {
                "time_step": 10,  # 10 seconds
                "total_time": 60  # 1 minute of simulation (6 steps)
            },
            "od_demand": [], 
            "nodes": [
                {"id": "START_A", "type": "source"},
                {"id": "START_B", "type": "source"},
                {"id": "MERGE_NODE", "type": "merge"},
                {"id": "END", "type": "sink"}
            ],
            "edges": [
                {
                    "id": "link_a",
                    "source": "START_A",
                    "target": "MERGE_NODE",
                    "length": 0.17, # Approx 1 cell length at 60mph and 10s dt
                    "lanes": 1,
                    "v": 60,
                    "q_max": 2000,
                    "k_jam": 150
                },
                {
                    "id": "link_b",
                    "source": "START_B",
                    "target": "MERGE_NODE",
                    "length": 0.17, 
                    "lanes": 1,
                    "v": 60,
                    "q_max": 2000,
                    "k_jam": 150
                },
                {
                    "id": "link_c",
                    "source": "MERGE_NODE",
                    "target": "END",
                    "length": 0.17, 
                    "lanes": 1,
                    "v": 60,
                    "q_max": 2000,
                    "k_jam": 150
                }
            ]
        }

    def tearDown(self):
        """
        Clean up the temporary configuration and generated output files after the test.
        """
        if os.path.exists(self.test_config_path):
            os.remove(self.test_config_path)
        if os.path.exists("ctm_matrices_output.xlsx"):
            os.remove("ctm_matrices_output.xlsx")

    def _write_config_and_run(self, config_dict):
        """Helper to write the config and run the network with heavily congested sources."""
        with open(self.test_config_path, 'w') as f:
            yaml.dump(config_dict, f)
            
        net = CTMNetwork(self.test_config_path)
        
        # Inject heavy demand into both upstream roads (for destination 0)
        net.nodes_state["START_A"].queue[0, 0] = 1000.0
        net.nodes_state["START_B"].queue[0, 0] = 1000.0
        
        net.run()
        return net

    def test_congested_merge_logic_equal(self):
        """
        Evaluate if identical upstream roads properly share receiving capacity evenly (50/50).
        """
        print("\n--- Running Integration Test: Congested Merge Logic (Equal) ---")
        
        # Add equal merge weights to the config for testing
        config = copy.deepcopy(self.base_config)
        config["edges"][0]["merge_weight"] = 1.0  # link_a
        config["edges"][1]["merge_weight"] = 1.0  # link_b
        
        net = self._write_config_and_run(config)
        
        y_a = net.edges_state["link_a"].y
        y_b = net.edges_state["link_b"].y
        y_c = net.edges_state["link_c"].y
        
        expected_q = 2000 * 1 * (10 / 3600.0) # ~5.5555...
        
        # Note: index [1, 1, 0] means time step 1, flow out of cell 0 for dest 0
        self.assertAlmostEqual(
            y_a[1, 1, 0], expected_q * 0.5, places=4, 
            msg="Link A should get exactly 50% of the downstream capacity at the merge."
        )
        self.assertAlmostEqual(
            y_b[1, 1, 0], expected_q * 0.5, places=4, 
            msg="Link B should get exactly 50% of the downstream capacity at the merge."
        )
        self.assertAlmostEqual(
            y_c[1, 0, 0], expected_q, places=4, 
            msg="Link C should be saturated and receive exactly its max capacity."
        )
        print("--- Integration Test Complete ---")

    def test_yield_merge_logic(self):
        """
        Evaluate if setting a merge ratio of 0 (yield sign) correctly forces one link
        to fully yield to the other when downstream is congested.
        """
        print("\n--- Running Integration Test: Yield Merge Logic (100/0) ---")
        
        config = copy.deepcopy(self.base_config)
        config["edges"][0]["merge_weight"] = 1.0  # link_a gets full priority
        config["edges"][1]["merge_weight"] = 0.0  # link_b yields completely
        
        net = self._write_config_and_run(config)
        
        y_a = net.edges_state["link_a"].y
        y_b = net.edges_state["link_b"].y
        
        expected_q = 2000 * 1 * (10 / 3600.0)
        
        self.assertAlmostEqual(
            y_a[1, 1, 0], expected_q, places=4, 
            msg="Link A should get 100% of the downstream capacity due to priority."
        )
        self.assertAlmostEqual(
            y_b[1, 1, 0], 0.0, places=4, 
            msg="Link B should get 0% of the downstream capacity (Yield constraint failed)."
        )
        print("--- Integration Test Complete ---")

    def test_low_priority_merge_logic(self):
        """
        Evaluate if a highly asymmetric priority ratio accurately distributes 
        capacity during congestion.
        """
        print("\n--- Running Integration Test: Low Priority Merge Logic (80/20) ---")
        
        config = copy.deepcopy(self.base_config)
        config["edges"][0]["merge_weight"] = 0.8  # link_a 
        config["edges"][1]["merge_weight"] = 0.2  # link_b 
        
        net = self._write_config_and_run(config)
        
        y_a = net.edges_state["link_a"].y
        y_b = net.edges_state["link_b"].y
        
        expected_q = 2000 * 1 * (10 / 3600.0)
        
        self.assertAlmostEqual(
            y_a[1, 1, 0], expected_q * 0.8, places=4, 
            msg="Link A should get 80% of the downstream capacity."
        )
        self.assertAlmostEqual(
            y_b[1, 1, 0], expected_q * 0.2, places=4, 
            msg="Link B should get 20% of the downstream capacity."
        )
        print("--- Integration Test Complete ---")

if __name__ == '__main__':
    unittest.main()