import unittest
import yaml
import os
import copy
import numpy as np

from cell_transmission_model import CTMNetwork

class TestIntegrationDivergeFlow(unittest.TestCase):
    def setUp(self):
        """
        Create a base custom network_config.yaml dictionary with a diverge topology.
        One upstream link diverging into two downstream links.
        """
        self.test_config_path = "temp_diverge_config.yaml"
        self.base_config = {
            "simulation": {
                "time_step": 10,  # 10 seconds
                "total_time": 60  # 1 minute of simulation (6 steps)
            },
            "od_demand": [], 
            "nodes": [
                {"id": "START", "type": "source"},
                {"id": "DIVERGE_NODE", "type": "diverge"},
                {"id": "END_B", "type": "sink"},
                {"id": "END_C", "type": "sink"}
            ],
            "edges": [
                {
                    "id": "link_a",
                    "source": "START",
                    "target": "DIVERGE_NODE",
                    "length": 0.17, # Approx 1 cell length at 60mph and 10s dt
                    "lanes": 1,
                    "v": 60,
                    "q_max": 2000,
                    "k_jam": 150
                },
                {
                    "id": "link_b",
                    "source": "DIVERGE_NODE",
                    "target": "END_B",
                    "length": 0.17, 
                    "lanes": 1,
                    "v": 60,
                    "q_max": 2000,
                    "k_jam": 150
                },
                {
                    "id": "link_c",
                    "source": "DIVERGE_NODE",
                    "target": "END_C",
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
        """Helper to write the config and run the network with 50/50 split demand."""
        with open(self.test_config_path, 'w') as f:
            yaml.dump(config_dict, f)
            
        net = CTMNetwork(self.test_config_path)
        
        # Inject heavy 50/50 demand into the single upstream source
        # Dest 0 corresponds to END_B, Dest 1 corresponds to END_C
        dest_idx_b = net.dest_to_index["END_B"]
        dest_idx_c = net.dest_to_index["END_C"]
        
        net.nodes_state["START"].queue[0, dest_idx_b] = 1000.0
        net.nodes_state["START"].queue[0, dest_idx_c] = 1000.0
        
        net.run()
        return net, dest_idx_b, dest_idx_c

    def test_uncongested_diverge_logic(self):
        """
        Evaluate if an uncongested diverge successfully splits demand 50/50 
        without artificially restricting the upstream flow.
        """
        print("\n--- Running Integration Test: Uncongested Diverge (50/50) ---")
        
        config = copy.deepcopy(self.base_config)
        net, dest_b, dest_c = self._write_config_and_run(config)
        
        y_a = net.edges_state["link_a"].y
        y_b = net.edges_state["link_b"].y
        y_c = net.edges_state["link_c"].y
        
        # expected_q for 2000 vph capacity = ~5.5555 vehicles per step
        expected_q = 2000 * 1 * (10 / 3600.0) 
        
        # Step 1: Link A tries to empty into Link B and Link C.
        # Since demand is 50/50 and both downstream links have capacity > expected_q/2,
        # Link A should be able to send its full expected_q.
        
        self.assertAlmostEqual(
            y_b[1, 0, dest_b], expected_q * 0.5, places=4, 
            msg="Link B should receive exactly half of Link A's full capacity."
        )
        self.assertAlmostEqual(
            y_c[1, 0, dest_c], expected_q * 0.5, places=4, 
            msg="Link C should receive exactly half of Link A's full capacity."
        )
        print("--- Integration Test Complete ---")

    def test_congested_fifo_diverge_logic(self):
        """
        Evaluate Daganzo's FIFO diverge logic: if one downstream link is congested, 
        it blocks the upstream cell, starving the other uncongested downstream link.
        """
        print("\n--- Running Integration Test: Congested FIFO Diverge ---")
        
        # Artificially restrict the capacity of Link C so it becomes a severe bottleneck
        config = copy.deepcopy(self.base_config)
        config["edges"][2]["q_max"] = 500  # Link C capacity reduced to 500 vph
        
        net, dest_b, dest_c = self._write_config_and_run(config)
        
        y_a = net.edges_state["link_a"].y
        y_b = net.edges_state["link_b"].y
        y_c = net.edges_state["link_c"].y
        
        # Link A and Link B capacity: ~5.5555 per step
        # Link C capacity: 500 * (10/3600) = ~1.3888 per step
        expected_q_a = 2000 * 1 * (10 / 3600.0)
        expected_q_c = 500 * 1 * (10 / 3600.0)
        
        # At Step 1, Link A has 5.5555 vehicles ready to leave (50% for B, 50% for C).
        # Link C can only accept 1.3888 vehicles. 
        # Under FIFO, the blocked vehicles heading to C ALSO block the vehicles heading to B!
        # Max flow out of A = min(S_a, R_b / P_b, R_c / P_c) = min(5.5555, 11.11, 1.3888 / 0.5) = 2.7777 total.
        
        restricted_total_flow = expected_q_c / 0.5
        
        # Link C receives exactly its maximum capacity
        self.assertAlmostEqual(
            y_c[1, 0, dest_c], expected_q_c, places=4, 
            msg="Link C should receive its absolute maximum capacity."
        )
        
        # Link B is STARVED. Even though it is empty and has a capacity of 5.5555,
        # it only receives its 50% share of the restricted total flow.
        self.assertAlmostEqual(
            y_b[1, 0, dest_b], restricted_total_flow * 0.5, places=4, 
            msg="Link B should be starved by the FIFO constraint caused by Link C."
        )
        
        # Verify that Link B received much less than it could have
        self.assertTrue(
            y_b[1, 0, dest_b] < (expected_q_a * 0.5),
            msg="FIFO logic failed: Link B received full flow despite Link C congestion."
        )
        
        print("--- Integration Test Complete ---")

    def test_strict_fifo_temporal_demand_diverge(self):
        """
        Evaluate the strict layer-by-layer FIFO logic against temporal demand changes.
        We create a scenario where the oldest vehicles in the diverge cell are
        headed to an open destination (B), while the newest vehicles are headed
        to a blocked destination (C).
        
        Aggregate Logic would prematurely block B because the overall cell has C-demand.
        Strict FIFO Logic will let B flow because B-bound vehicles are at the front of the queue.
        """
        print("\n--- Running Integration Test: Temporal Demand Strict FIFO Diverge ---")
        
        config = copy.deepcopy(self.base_config)
        
        # Link A capacity: 10 veh/step
        config["edges"][0]["q_max"] = 3600 
        # Link B capacity: 2 veh/step (bottlenecked but open)
        config["edges"][1]["q_max"] = 720  
        # Link C capacity: 0 veh/step (completely blocked)
        config["edges"][2]["q_max"] = 0    
        
        with open(self.test_config_path, 'w') as f:
            yaml.dump(config, f)
            
        net = CTMNetwork(self.test_config_path)
        dest_b = net.dest_to_index["END_B"]
        dest_c = net.dest_to_index["END_C"]
        
        # We must use the demand_profile for secondary injections so they aren't
        # overwritten by the simulation's internal node queue update loop.
        if not hasattr(net, 'demand_profile'):
            net.demand_profile = {}
        if "START" not in net.demand_profile:
            total_steps = int(config["simulation"]["total_time"] / config["simulation"]["time_step"])
            net.demand_profile["START"] = np.zeros((total_steps, len(net.dest_to_index)))
        
        # Step 0: Inject 5 B vehicles directly into the queue so they enter Link A immediately.
        net.nodes_state["START"].queue[0, dest_b] = 5.0
        
        # Step 0 (Demand Profile): Inject 5 C vehicles. This ensures they are added to 
        # queue[1] during the step 0 update, and will enter Link A BEHIND the B vehicles at Step 1.
        net.demand_profile["START"][0, dest_c] = 5.0
        
        net.run()
        
        y_b = net.edges_state["link_b"].y
        
        # At step 1, 2 of the 5 B vehicles should exit Link A into Link B.
        self.assertAlmostEqual(
            y_b[1, 0, dest_b], 2.0, places=4,
            msg="At Step 1, Link B should receive its capacity of 2 vehicles."
        )
        
        # At step 2, Link A contains 3 B vehicles (old) and 5 C vehicles (new).
        # Aggregate logic would stall completely here because P_c = 5/8 and R_c = 0.
        # Strict FIFO should process the 3 old B vehicles first, allowing 2 more to enter Link B.
        
        print(f"Flow to B at step 2: {y_b[2, 0, dest_b]}")
        
        self.assertGreater(
            y_b[2, 0, dest_b], 0.0,
            msg="Strict FIFO Failed: B vehicles at the front were blocked by newer C vehicles."
        )
        self.assertAlmostEqual(
            y_b[2, 0, dest_b], 2.0, places=4,
            msg="Strict FIFO Failed: Link B should receive exactly its capacity of 2 vehicles."
        )
        
        print("--- Integration Test Complete ---")

if __name__ == '__main__':
    unittest.main()