# Sports taxonomy fixture

`sports_taxonomy.pkl` is a self-contained copy of the sports subset used for
search and graph-construction evaluations. It bundles the category tree from
`semgraph/sport_tree.pkl`, 211 articles from `semgraph/sports.json`, and 609
questions with evidence from `semgraph/sports_q.json`. The source file SHA-256
hashes are stored in the pickle.

The pickle contains only Python dictionaries, lists, strings, numbers, and
`None`; loading it does not require `semgraph` classes. `tree.nodes` preserves
each original node ID, name, text, text ID, metadata, parent ID, and ordered
child IDs. An article may appear under more than one category. The original
tree has one parent per nonroot node; experiments may interpret each parent
edge as `SUBTYPE_OF`, but this fixture does not prescribe graph entities or
retrieval policy.

`pilot_question_indices` holds the ten zero-based question indices used in the
initial search pilot. Use the full question set or a fresh split for future
evaluation. The fixture contains article text, so load it only from this
trusted repository checkout.
