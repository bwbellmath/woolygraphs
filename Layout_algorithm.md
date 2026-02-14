Phase 1: Initial Layout:

Data Structure: Stitch Descriptions: 

# cursor position is (0,0)
{ "k" : { "character"  : "k",
          "cursor_inc"  : 0,
	  "keep"        : True,
	  "add"         : 1,
	  "extra"       : 0,
          "edge_list"   : [{ "v" : (-1, 0), "orient" : "h", "bk" : "k", "length" : 1.0},
                           { "v" : (0, -1), "orient" : "v", "bk" : "b", "length" : 1.0}],
	  "cursor_dir"  : False},
  "co" : { "character"  : "k",
          "cursor_inc"  : 0,
	  "keep"        : True,
	  "add"         : 0,
	  "extra"       : 1,
          "edge_list"   : [{ "v" : (-1, 0), "orient" : "h", "bk" : "k", "length" : 1.0}],
	  "cursor_dir"  : False},
  "bo" : { "character"  : "p",
          "cursor_inc"  : 0,
	  "keep"        : False,
	  "add"         : 0,
	  "extra"       : 0,
          "edge_list"   : [{ "v" : (-1, 0), "orient" : "h", "bk" : "k", "length" : 1.0},
                           { "v" : (0, -1), "orient" : "v", "bk" : "b", "length" : 1.0}],
	  "cursor_dir"  : False},

  "p" : { "character"  : "p",
          "cursor_inc"  : 0,
	  "keep"        : True,
	  "add"         : 1,
	  "extra"       : 0,
          "edge_list"   : [{ "v" : (-1, 0), "orient" : "h", "bk" : "k", "length" : 1.0},
                           { "v" : (0, -1), "orient" : "v", "bk" : "b", "length" : 1.0}],
	  "cursor_dir"  : False},
  "kfb" : { "character"  : "k",
          "cursor_inc"  : 0,
	  "keep"        : True,
	  "add"         : 1,
	  "extra"       : 0,
          "edge_list"   : [{ "v" : (-1, 0), "orient" : "h", "bk" : "k", "length" : 1.0},
                           { "v" : (0, -1), "orient" : "v", "bk" : "b", "length" : 1.0}],
	  "cursor_dir"  : False},
  "k2tog" : { "character"  : "k",
          "cursor_inc"  : 0,
	  "keep"        : True,
	  "add"         : 1,
	  "extra"       : 0,
          "edge_list"   : [{ "v" : (-1, 0), "orient" : "h", "bk" : "k", "length" : 1.0},
                           { "v" : (0, -1), "orient" : "v", "bk" : "b", "length" : 1.0},
                           # TODO : the geometry to figure out how long
			   #these stitches need to be
                           { "v" : (1, -1), "orient" : "v", "bk" : "b", "length" : 1.0}],
	  "cursor_dir"  : False},
  "turn" : { "character"  : "k",
          "cursor_inc"  : 0,
	  "keep"        : True,
	  "add"         : 0,
	  "extra"       : 0,
          "edge_list"   : [],
	  "cursor_dir"  : True}
}

Need to add: normal vector (default (0,0,1)), right-left vector (default (left_stitch_pos - right_stitch_pos) / norm(left_stitch_pos - right_stitch_pos)), up-down vector (default (normal x right_left)). 

Need to specify several offsets: 

This stitch's position in the normal direction (default 0) relative to the left-right vector's closest point to the normal vector eminating from this stitch. 

This stitch's position in the right-left direction (default 0) relative to the normal vector's closest point to the right-left vector eminating from this stitch. 

This stitch's position in the up-down direction (default 0) relative to the normal vector's closest point to the up-down vector eminating from this stitch. 

For a knit stitch, the normal direction position is a slight positive deformation -- let's set that default to 0.1 * stitch_height. 

For a make 1, the up-down perturbation is 0.1*stitch height. for any reduction in stitches, the up-down perturbation is -0.1*stitch height. 

Data Structure: Layout Stitch

Data structure for layout: Following the stitch descriptions, we must create a data structure that represents the layout of the stitches. 

This data structure needs to include the following information for each stitch:

- Stitch type
- Stitch position (x,y,z)
- Stitch normal vector (x,y,z)
below links (list of stitch indices + associated edge length info)
<!-- - Stitch above links (list of stitch indices + associated edge length info)
- Stitch left links (list of stitch indices + associated edge length info) -->

Note that the stitch objects for layout need two types of information: information that is fixed for their stitch type (e.g. the desired offset for their stitch type, etc...This should be inherited and ultimately be defined in the above json description. Second, we need to keep track of the identity of this stitch (index) and the very few variables that determine the stitche's real position (x,y,z coordinates, normal vector -- I think that's all that's needed mathematically but if anything is unconstrained, we can adjust), and finally the stitch needs the ids of the stitches connected to it -- these edge connections should have lengths inherrited from their stitch descriptions and those lengths can either be explicitly specified here or used in reference to theit stitch descriptions. 

Most of what is currently listed for each stitch are properties that are NOT fixed but actually must be determined live based on the few fully determined properties

(Note that since we knit right to left, during construction we only need to keep track of the below and right links -- also called the "back" links, during construction -- and the "front" links, which are the above and left links, will be constructed in the next row and do not need to be redundantly stored since thy will already be stored as the "back" links of the next row for the graph layout)

Algorithm: Initial Layout

Knitting can be thought of as a language compilation where the stitches are the source code and the edge-length stitch graph, layout with precise positions, and other instantiation are the compiled code. Our goal in this first layout stage is to create instances of each specified stitch from a sequence of shorthand stitches (e.g. "k 12, p 12, turn") where each stitch instance is created corresponding to the stitch description in the json file, and the stitch instance is connected to the previous stitch instance in the sequence by an edge of the appropriate length and orientation. In addition, we need to specify initial configurations for the stitch's position and normal vector. 

We will start with a single stitch at the origin (0,0,0) with a normal vector of (0,0,1) (note that the right-left vector is determined by the previous stitch's normal vector and the previous stitch's right-left vector -- see above for details, but these are determined rather than being specified and therefore fixed). 

For each new stitch added, we will determine its position and normal vector based on the previous stitch's position and normal vector, and the edge connecting the previous stitch to the new stitch -- how to do this is specified in my above detailed stitch descriptions including a complex indexing scheme for which stitches *below* and *behind* the original stitch are connected to the new stitch. The point of this very complex indexing system is to accomodate advanced structures like a k5below, k4tog, cables, etc... We will gradually expand and refine this system as we run into more complex stitches. 

Phase 2: Refining the layout to model useful physicsl properties of knitting

The goal in this phase is to produce a 3D layout of the stitches that models the physical structure of the knitted fabric. The goal for this representation is to get as close as possible to the physical appearance of the finished knit object as possible in several contexts. The initial layout will be used to define the base shape of the object in phase 1 (which may violate some key properties like our desired edge lengths etc...). This second phase will pick a physical domain (option 1: 0-gravity neutral layout of the relaxed fabric, option 2: draped over a manequin with a few specified stitches anchored to the manequin (We'll need to grab a manequin from thingaverse), option 3: blocked flat -- see below.)

This algorithm is based on specified relative offsets and positions of stitches. We will use an optimizer (staring with pytorch) to actually set the positions of the stitches and thir normal vectors. The default is to enumerate (within our optimizer) the edge vectors (point - point), calculate their lengths ||(point - point)|| and then create a loss based on their deviation from a specified length: |specified_length - ||(point - point)||_2|. Second, we want to apply some regulatization to maintain the desired flatness/orientation of the fabric -- Now each of the offsets we specified relative to the normal, left-right, and up-down vectors can be accumulated as a separate loss term. We want to set things up so that the edge lengths are a very strong requirement and we want to optimize the secondary losses only in so far that they do not mess up the edge lengths.

Normal Coherence Regularization: We want nearby stitches to follow the same surface. For every pair of stitches (i, j) connected by an edge in the graph, we apply a regularization loss that pushes their normal vectors to be aligned:

  L_normal_coherence = lambda_coherence * sum_{(i,j) in E} (1 - n_i . n_j)

When n_i and n_j are perfectly aligned, n_i . n_j = 1 and the loss is 0. When they diverge, the loss grows. This keeps the fabric behaving as a locally smooth surface -- neighboring stitches should agree on which way "out" is. The weight lambda_coherence is a configurable parameter for each knit object, since some objects (e.g. flat stockinette) want very strong coherence, while objects with intentional curvature (e.g. a hat crown) may want to relax it.

"Blocked Flat" Mode: Some knit objects (e.g. a pi-shawl, lace shawls in general) are meant to be blocked flat -- pinned out on a blocking board so the fabric stretches into a flat, regular shape. In this mode, the physical domain is a plane and the optimizer's priorities are inverted:

  - Edge lengths become SOFT constraints (low lambda_edge). The yarn stretches to accommodate the desired shape -- this is physically what blocking does.
  - Flatness becomes the HARD constraint (high lambda_flat). All z-coordinates are pinned to 0 (or a fixed plane), or equivalently we add a very strong penalty: L_z = lambda_z * sum_i z_i^2.
  - Regularity / even spacing becomes important: we want stitches to fan out evenly, especially for shawls where increases create a wedge or circular shape. This can be achieved by adding an angular uniformity loss that penalizes uneven angular spacing of edges around each vertex.
  - Normal coherence (see above) is maximally strong in this mode since the entire object should agree on normal = (0,0,1).

The blocked-flat mode essentially solves a 2D layout problem: find (x,y) positions for each stitch such that the graph is laid out regularly in the plane, with edge lengths allowed to stretch as needed. The rest lengths from the stitch descriptions serve as soft guides rather than hard targets.

I am not sure which approach will work best for this setup: My initial preference is to just define these loss functions (and check for anything that is unconstrained) and then use Adam to just optimize with pytorch. This should be part of our initial development of the code. In the second iteration, we can take the converging positions that we achieve from these layouts and try to replicate them much more quickly with graph neural networks, direct force computations/relaxations, and other methods.

All lambda weights (lambda_edge, lambda_normal, lambda_offset, lambda_flat, lambda_repulsion, lambda_coherence, lambda_z, etc.) should be configurable parameters that can be set per knit object, since different objects have very different physical requirements.

Phase 3: Display

We want a webui to actually display these completed graphs so that we can view the resulting object and rotate it in space. In a second iteration we will want to add the ability to modify the color of stitches by mouse clicks, and in a third iteration we will want to be able to modify the character of stitches and also to add or remove stitches of any type with automated dialogues to specify how to connect any new or disconnected stitches. In a fourth iteration we will want to use the stitch descriptions to generate a yarn-graph (directed graph enumerating the path of the yarn) and then to create a continuous tubular rendering of the yarn throughout the object which we can turn on to provide a higher fidelity rendering. 


