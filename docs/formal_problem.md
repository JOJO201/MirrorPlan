# Formal Problem

Let `G=(V,E)` be a directed dependency graph where `(u,v)` means that model `v`
declares model `u` as an input ancestor. Let `D subset V` be repositories that
become unavailable in a deletion event. The candidate set is
`C={u in D : u has a surviving descendant}`.

For every surviving affected model `v`, define the requirement set

`R_v = Anc_G(v) intersect D`.

Under a selected mirror set `S subset C`, `v` has a complete declared lineage
exactly when `R_v subset S`. With nonnegative target weights `w_v`, costs `c_u`,
and budget `B`, the optimization problem is

`maximize sum_v w_v [R_v subset S]`

subject to `sum_{u in S} c_u <= B`.

The empirical study uses `w_v=1` and `c_u=1` because the public snapshots do
not archive repository byte sizes.

## Complexity

With unit costs and requirement sets of cardinality two, each candidate is a
vertex and each target requirement is an edge. Selecting `B` candidates to
maximize fully contained requirements is exactly Densest-k-Subgraph. Therefore
the decision problem is NP-hard. The general problem is a weighted
Densest-k-Subhypergraph instance.

The objective is monotone but not submodular. For one requirement `{a,b}`, the
marginal gain of adding `a` is zero at the empty set and positive after `b` is
selected, violating diminishing returns. Standard maximum-coverage guarantees
therefore do not apply.

Individual-impact ranking has no positive multiplicative guarantee even for
unit costs, unit target weights, rank-two requirements, and budget two. For any
integer `t`, create `t` targets requiring `{a,b}`. Create candidates `x,y` with
`t+1` distinct unit-weight requirements `{x,p_i}` and `{y,q_i}`. Impact ranks
`x,y` above `a,b` and obtains zero, while selecting `{a,b}` obtains `t`.

## Complementarity core

Define the complementarity core

`K = union {R_v : |R_v| >= 2}`.

Every candidate outside `K` occurs only in a singleton requirement. Let `a_u`
be the aggregate weight of the singleton targets requiring tail candidate `u`.
For any fixed number `b` of tail candidates, the exact tail solution is the `b`
largest values `a_u`. The core interaction graph decomposes into components
`Q_1,...,Q_h`; all requirements involving a core candidate stay inside one such
component. If `F_i(b)` is the exact value of component `i` at local budget `b`
and `P_T(b)` is the prefix sum of the `b` largest tail weights, then

`OPT(B) = max_{b_0+...+b_h <= B} P_T(b_0) + sum_i F_i(b_i)`.

This is a lossless decomposition, not a relaxation. With unit costs and
enumerated core components, CoreFactor runs in

`O(|T| log |T| + sum_i |Q_i| 2^{|Q_i|} + h B^2)`.

Components above the enumeration threshold use exact local MILP frontiers.
The independent global MILP checks every reported objective.

## Lineage charge certificates

For each aggregated requirement `e` of weight `w_e`, assign nonnegative
charges `alpha_eu` to its members such that

`sum_{u in e} alpha_eu = w_e`.

Candidate `u` receives load
`ell_u = sum_{e containing u} alpha_eu`. For every plan of size at most
`B`, its objective is no larger than the sum of its candidate loads, which is
no larger than the sum `U_B(alpha)` of the `B` largest loads. Minimizing
`U_B` over valid charges equals the natural LP relaxation

`maximize sum_e w_e y_e`

subject to `y_e <= x_u` for every `u in e`,
`sum_u x_u <= B`, and `x,y in [0,1]`.

For integer weights, a feasible value `L=floor(U_B)` proves global
optimality. Certificates use scale `10^9`: each group distributes exactly
`10^9 w_e` nonnegative integer units. The verifier recomputes the selected
value, charge conservation, candidate loads, and top-`B` sum using integer
arithmetic. Floating-point LP output is only a proof generator and is outside
the trusted chain.

If a root LP integrality gap remains, a binary proof branches on whether an
undecided candidate is selected. At each leaf, already completed groups form a
constant and the same charge bound applies to the residual groups under the
remaining budget. Every feasible plan follows one unique branch path, so
closing all leaf integer bounds at value `L` proves `L` globally optimal.
Conversely, branching on every candidate yields a complete proof system: at a
full-assignment leaf the residual problem is empty and the leaf bound is the
assignment's exact value. Thus every globally optimal plan admits a closing
tree of depth at most `|C|`, although its worst-case size can be exponential.

## Incomplete-alert loss identity

For alerted candidates `A`, let `W` be the all-candidate objective,
`H(A)` the weight of requirements wholly contained in `A`, `O(A,B)` the
exact alert-restricted value, and `L(A,B)` the deployed Bundle value. Define

- alert gap: `W - H(A)`;
- capacity gap: `H(A) - O(A,B)`;
- allocation gap: `O(A,B) - L(A,B)`.

All three terms are nonnegative and, with recovered value `L(A,B)`, sum
exactly to `W`. The identity is conditional on an alert set and does not make
the alert mechanism causal or predictive.

## FactorExact

Construct the candidate interaction graph: two candidates are adjacent when
they co-occur in at least one requirement set. Every requirement lies wholly in
one connected component. For each component of size `q`, encode local
requirement weights by bit mask and apply a subset zeta transform in
`O(q 2^q)` time to obtain the exact value of every selected subset. Retain the
best local subset at each cost and combine component frontiers with knapsack
dynamic programming.

For unit costs, the total runtime is

`O(sum_i q_i 2^{q_i} + m B^2)`,

where `q_i` are interaction-component sizes and `m` is their number. The method
is fixed-parameter tractable in the largest interaction component. A global
binary MILP serves as an independent exact oracle.
