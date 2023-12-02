import networkx as nx
import matplotlib as pyplot
from networkx.drawing.nx_agraph import graphviz_layout

g = nx.drawing.nx_pydot.read_dot("dot/lace_scarf.dot")

posit = nx.planar_layout(g)

for n in g.nodes(data=True):
    n[1]['x'] = posit[n[0]][0]
    n[1]['y'] = posit[n[0]][1]
    print(n)

nx.drawing.nx_pydot.write_dot(g, "posit_dot/lace_scarf.dot")