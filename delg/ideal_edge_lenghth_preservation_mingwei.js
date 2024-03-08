function bestScalingForEdgeLengthPreservation(links, lengths){
  let s = 1; //find best scaling factor
  let num = 0; // = np.sum([ideal_edge_length[k]**2/actual_edge_length[k] for k in g.edges])
  let den = 0; // np.sum([ideal_edge_length[k] for k in g.edges])
  for (let i = 0; i < links.length; i++) {
    let x1 = links[i].source.x;
    let y1 = links[i].source.y;
    let x2 = links[i].target.x;
    let y2 = links[i].target.y;
    let [dx, dy] = [(x1-x2), (y1-y2)];
    let al = Math.sqrt(dx*dx + dy*dy); //actual length
    let il = parseFloat(lengths[i]); //ideal length
    num += (il*il) / al;
    den += il;
  }
  s = num / den;
  return s;
}

function ideal_edge_length_preservation(links, ideal_lengths){
  let total_difference = 0;
  let s = bestScalingForEdgeLengthPreservation(links, ideal_lengths)
  for (let i = 0; i < links.length; i++) {
    let x1 = links[i].source.x;
    let y1 = links[i].source.y;
    let x2 = links[i].target.x;
    let y2 = links[i].target.y;
    let dist = Math.sqrt((x1-x2)*(x1-x2) + (y1-y2)*(y1-y2));
    //let dist = 16*Math.sqrt((x1-x2)*(x1-x2) + (y1-y2)*(y1-y2));
    let diff = Math.abs(ideal_lengths[i] - dist);
    total_difference += Math.pow(diff / ideal_lengths[i], 2);
  }
  let average_difference = Math.sqrt(total_difference / links.length);
  //return 1-average_difference;
  return average_difference;
}
