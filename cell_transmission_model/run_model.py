from cell_transmission_model import CTMNetwork, export_to_excel
from cell_transmission_model.visualizations import plot_results


net = CTMNetwork("network_config_demand_meter.yaml")
net.run()

# Explicitly save the state matrices to an Excel file
#export_to_excel(net.edges_state, filename="baseline_demand_meter.xlsx", disaggregated=True)

plot_results(net, ["SegAB", "SegBC", "SegCD"])
plot_results(net, ["SegFG"])
