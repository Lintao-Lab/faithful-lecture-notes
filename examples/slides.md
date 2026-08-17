# Example slides — "Introduction to Graph Theory" (fictional)

> Fictional companion slides for the example transcript, written in the format this
> pipeline's converters produce (one `## Slide N` heading per slide). Entirely
> synthetic; created only so the pipeline can be smoke-tested without real course
> material.

## Slide 1
Introduction to Graph Theory
MATH1101 Discrete Mathematics (fictional course)
Dr Ada Kowalski

## Slide 2
Today
- What a graph is (formally)
- The Handshaking Lemma
- Graph isomorphism and invariants

## Slide 3
Definition
A graph is an ordered pair G = (V, E):
- V: a set of vertices (nodes)
- E: a set of edges, each an unordered pair {u, v} of distinct vertices
Simple graph: no loops, no repeated edges.

## Slide 4
Running example: the workshop graph
Vertices: five people at a workshop
Edges: handshakes between pairs of people

## Slide 5
Degree
deg(v) = number of edges incident with vertex v
Workshop picture: deg(person) = number of hands they shook

## Slide 6
Handshaking Lemma
For every graph G = (V, E): sum of deg(v) over all v in V equals 2|E|.
Proof idea: every edge has two ends, so it contributes 2 to the degree sum.

## Slide 7
Corollary
In any graph, the number of vertices of odd degree is even.

## Slide 8
Isomorphism
G and H are isomorphic if some bijection f: V(G) → V(H) preserves adjacency:
{u, v} in E(G) if and only if {f(u), f(v)} in E(H).
Informally: same structure, different labels.

## Slide 9
Isomorphism in practice
Quick checks (invariants): |V|, |E|, sorted degree sequence.
Warning: invariants can only rule out isomorphism, never confirm it.

## Slide 10
Reminders
- Problem set 1 due Friday 5 pm (course website)
- Next lecture: paths, cycles, connectivity
