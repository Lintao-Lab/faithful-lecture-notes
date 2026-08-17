# Example transcript — "Introduction to Graph Theory" (fictional)

> This is a small, entirely fictional mini-lecture created for smoke-testing the
> pipeline. It is not real course material. The fictional lecturer is "Dr Ada
> Kowalski" and the fictional course is MATH1101. The whole "lecture" is about
> ten minutes long.

[00:00] Dr Kowalski: Good morning, everyone. Let's get started. Today is our first
lecture on graph theory, which is arguably the most useful branch of discrete
mathematics you will meet in this course. By the end of this lecture you should be
able to define what a graph is, state the Handshaking Lemma, and explain what makes
two graphs "the same" in the sense of isomorphism.

[00:48] Dr Kowalski: First things first: a graph is not a chart. When I say "graph"
in this course I do not mean a bar chart or a plot of a function. A graph is an
ordered pair G = (V, E), where V is a set of vertices — also called nodes — and E is
a set of edges, each edge being an unordered pair of distinct vertices. If you take
one thing away from today, take that formal definition; everything else is built on
it.

[02:10] Dr Kowalski: Let's make this concrete. Picture five people at a workshop.
The vertices are the people, and an edge joins two vertices if those two people
shook hands. Nobody shakes their own hand — that's why our edges join distinct
vertices, so this is what we call a simple graph. No loops, no repeated edges.

[03:05] Dr Kowalski: The degree of a vertex is simply the number of edges touching
it. In our workshop picture, the degree of a person is the number of hands they
shook. And here is the first theorem of the course, the Handshaking Lemma: in any
graph, the sum of the degrees of all vertices equals twice the number of edges. Why?
Because every edge has two ends, so it contributes exactly two to the total degree
count. One edge, two ends — that is the entire proof idea, and yes, I will expect
you to reproduce this argument in the mid-semester test.

[04:40] Student A: Does the lemma still hold if the graph has loops?

[04:52] Dr Kowalski: Good question. With a loop you must count it as contributing
two to the degree of its vertex, and then the lemma still goes through — but we will
stay with simple graphs this week, so don't worry about loops for now.

[05:30] Dr Kowalski: An immediate consequence, and this one matters: in any graph,
the number of vertices of odd degree is even. Try it on a few examples tonight and
convince yourself. This is sometimes called the Handshaking Corollary, and it is a
classic exam-style one-liner.

[06:25] Dr Kowalski: Next concept: when are two graphs really the same graph drawn
differently? We say G and H are isomorphic if there is a bijection between their
vertex sets that preserves adjacency — an edge exists between two vertices of G if
and only if an edge exists between their images in H. Think of it as relabelling the
vertices without changing the structure.

[07:50] Dr Kowalski: A practical warning: checking isomorphism by brute force is
expensive, so in practice we first compare invariants — number of vertices, number
of edges, the sorted list of degrees. If two graphs disagree on any invariant, they
cannot be isomorphic. If they agree on all of them, that proves nothing by itself;
invariants can rule out isomorphism but cannot confirm it. That direction of the
logic trips people up every year, so underline it in your notes.

[09:10] Dr Kowalski: Two administrative items before we finish. First, problem set
1 is due this Friday at 5 pm via the course website — it covers today's definitions
and the Handshaking Lemma. Second, next lecture we will look at paths, cycles, and
connectivity, which builds directly on today's degree concept, so do the problem set
before then. See you on Thursday.
