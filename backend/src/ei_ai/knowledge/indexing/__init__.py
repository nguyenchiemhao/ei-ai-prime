"""Vector indexing of ready documents into the Organization's partition (EA-35, KB-04).

``job`` embeds the chunks of a ready document through the Model Gateway and replaces its vectors,
tagged with the collection's permission metadata and the embedding model. See
``docs/architecture/model-gateway.md`` for the embedding server and how to change the model.
"""
