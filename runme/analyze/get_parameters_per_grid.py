# Must be run after get_parameters_per_plz.py
from src.analysis.topology_analysis import ParameterCalculator

plz = 80803
pc = ParameterCalculator()
pc.calc_parameters_per_grid(plz)