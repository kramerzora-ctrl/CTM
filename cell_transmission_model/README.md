# Installation and Environment Setup

This project uses a standard Python package structure, with the main library code located in the `src/cell_transmission_model` directory.

You can set up your virtual environment and install the library using either `uv` (recommended) or `conda`.

## Option 1: Using `uv` (Recommended)

If you are using `uv`, setting up the environment and installing the dependencies is trivial:

```
# Navigate to the root of the project folder
cd your-repo-name

# Sync the project (creates a virtual environment and installs the package)
uv sync
```

## Option 2: Using `conda`

If you prefer to use `conda` for environment management, you can create a virtual environment and install the library in editable mode using `pip`:

```
# 1. Navigate to the root of the project folder
cd your-repo-name

# 2. Create a new conda environment (Python 3.10 or newer is recommended)
conda create -n ctm_env python=3.10 -y

# 3. Activate the environment
conda activate ctm_env

# 4. Install the library in editable mode
pip install -e .
```

By running `pip install -e .` from the root of the repository (where the `pyproject.toml` file is located), the `cell_transmission_model` package will be linked to your active environment. This allows you to import it seamlessly in your scripts while instantly reflecting any changes you make to the source code.

# Cell Transmission Model (CTM) Network Setup Guide

This guide explains how to configure a macroscopic traffic network for the CTM simulation using a YAML configuration file.

The configuration file defines the simulation parameters, the physical road network (nodes and edges), time-dependent origin-destination (OD) demand, and dynamic metering schedules.

## 1. Simulation Parameters

The `simulation` block defines the global time settings for your run.

```
simulation:
  time_step: 3      # The duration of each simulation tick (in seconds)
  total_time: 7200  # Total duration of the simulation (in seconds)
```

_Note: To avoid fractional cells, it is highly recommended to choose a `time_step` that divides evenly into your segment lengths based on the free-flow speed._

## 2. Nodes (The Junctions)

Nodes act as the connection points, boundaries, and decision centers of the network. Nodes do not have physical length; they simply route flow between edges.

Every node requires an `id` and a `type`. The available types are:

- **`source`**: The origin point where vehicles enter the network. Acts as an infinite vertical queue.
    
- **`sink`**: The destination point where vehicles exit the network.
    
- **`diverge`**: A junction where one incoming edge splits into two or more outgoing edges (e.g., an off-ramp).
    
- **`merge`**: A junction where two or more incoming edges combine into one outgoing edge (e.g., an on-ramp).
    
- **`meter`**: A simple 1-in, 1-out node that dynamically restricts flow based on a defined schedule.
    

## 3. Edges (The Road Segments)

Edges represent the physical stretches of road connecting the nodes. The simulation automatically discretizes these edges into cells based on the `time_step` and the free-flow speed (`v`).

Each edge requires the following parameters:

- **`id`**: Unique identifier for the road segment.

- **`source`**: The ID of the node where this edge begins.
    
- **`target`**: The ID of the node where this edge ends.
    
- **`length`**: Physical length of the segment (in miles).
    
- **`lanes`**: Number of lanes.
    
- **`v`**: Free-flow speed (in mph).
    
- **`q_max`**: Maximum flow capacity per lane (in vehicles/hour/lane).
    
- **`k_jam`**: Maximum jam density per lane (in vehicles/mile/lane).
    

## 4. Setting Up Specific Configurations

### Diverges (Off-Ramps)

To create a diverge, point one edge into a `diverge` node, and point two or more edges out of it. The simulator uses strict FIFO logic to route vehicles to their destinations.

```
nodes:
  - id: "NODE_OFF_RAMP"
    type: "diverge"
# Edges: mainline_seg1 points TO "NODE_OFF_RAMP". mainline_seg2 and off_ramp point FROM it.
```

### Merges (On-Ramps)

To create a merge, point two or more edges into a `merge` node, and one edge out of it. **Important:** You must define a `merge_weight` on the incoming edges to dictate priority when the junction is congested.

```
  - id: "mainline_seg2"
    source: "NODE_OFF_RAMP"
    target: "NODE_ON_RAMP"
    # ... other parameters ...
    merge_weight: 2.5  # Mainline gets 2.5x the priority of the ramp

  - id: "on_ramp_link"
    source: "ON_RAMP_METER"
    target: "NODE_ON_RAMP"
    # ... other parameters ...
    merge_weight: 1  # Ramp has lower priority to mainline
```

### Meters (Traffic Lights / Ramp Meters)

To restrict flow dynamically, place a `meter` node on an approach. You then define a `meter_schedule` block at the root of your YAML file to control its capacity over time.

```
nodes:
  - id: "ON_RAMP_METER"
    type: "meter"

meter_schedule:
  - node: "ON_RAMP_METER"
    start_time: 900     # Time in seconds
    end_time: 3600      # Time in seconds
    rate: 840           # Restricted flow rate in veh/hr
```

## 5. Origin-Destination (OD) Demand

Demand is injected into `source` nodes and routed to `sink` nodes based on an explicitly defined OD matrix.

```
od_demand:
  - origin: "START"
    destination: "END"
    start_time: 0
    end_time: 3600
    rate: 4600  # veh/hr wanting to make this specific trip
```

## Complete Example Topology

Here is a simplified, generic configuration modeling a mainline freeway with one off-ramp, followed by an on-ramp equipped with a ramp meter.

```
simulation:
  time_step: 3  
  total_time: 7200  

od_demand:
  - origin: "START"
    destination: "END"
    start_time: 0
    end_time: 3600
    rate: 4600  
  - origin: "START"
    destination: "OFF_RAMP_SINK"
    start_time: 0
    end_time: 1800
    rate: 500  
  - origin: "ON_RAMP_SOURCE"
    destination: "END"
    start_time: 0
    end_time: 3600
    rate: 900  

meter_schedule:
  - node: "ON_RAMP_METER"
    start_time: 450
    end_time: 5400
    rate: 700  
  
nodes:
  - id: "START"
    type: "source"
  - id: "NODE_OFF_RAMP"
    type: "diverge"
  - id: "NODE_ON_RAMP"
    type: "merge"
  - id: "END"
    type: "sink"
  - id: "OFF_RAMP_SINK"
    type: "sink"
  - id: "ON_RAMP_SOURCE"
    type: "source"
  - id: "ON_RAMP_METER"  
    type: "meter"

edges:
  - id: "mainline_seg1"
    source: "START"
    target: "NODE_OFF_RAMP"
    length: 3.0 
    lanes: 3
    v: 60 
    q_max: 1800 
    k_jam: 120 

  - id: "off_ramp"
    source: "NODE_OFF_RAMP"
    target: "OFF_RAMP_SINK"
    length: 0.1 
    lanes: 1
    v: 60
    q_max: 1800
    k_jam: 120

  - id: "mainline_seg2"
    source: "NODE_OFF_RAMP"
    target: "NODE_ON_RAMP"
    length: 1.0 
    lanes: 3
    v: 60
    q_max: 1800
    k_jam: 120
    merge_weight: 2.5  

  - id: "on_ramp"
    source: "ON_RAMP_SOURCE"
    target: "ON_RAMP_METER" 
    length: 0.4 
    lanes: 1
    v: 45
    q_max: 1500
    k_jam: 120

  - id: "on_ramp_meter_link" 
    source: "ON_RAMP_METER"
    target: "NODE_ON_RAMP"
    length: 0.1 
    lanes: 1
    v: 60
    q_max: 1800
    k_jam: 120
    merge_weight: 0.5  

  - id: "mainline_seg3"
    source: "NODE_ON_RAMP"
    target: "END"
    length: 2.0 
    lanes: 3
    v: 60
    q_max: 1800
    k_jam: 120
```

# To run the model

All you have to do is properly configure your scenario using the YAML file format, load it and export the results. A very simple plot_results function is provided for visualization convenience. 


```
from cell_transmission_model import CTMNetwork, export_to_excel
from cell_transmission_model.visualizations import plot_results


net = CTMNetwork("network_config.yaml")
net.run()

# Explicitly save the state matrices to an Excel file
export_to_excel(net.edges_state, filename="baseline.xlsx", disaggregated=True)

plot_results(net, ["mainline_seg1", "mainline_seg2", "mainline_seg3"])
plot_results(net, ["on_ramp"])
```

# Post processing

The code above generate a basline.xlsx excel file. Each sheet in that file represents the accumulation or flow matrix for a given road segment. `disaggregated=True` creates accumulation matrices for each vehicle cohort by destination. It will be your job to interpret those results and use them to compute the average travel time and system outflow.


