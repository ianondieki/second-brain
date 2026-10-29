"""Profile and problem embeddings for the ranker's f1 (REQ-PERS-01, REQ-PERS-02, REQ-EMB-01; P23-1).

Revision 0012's owner-run functions do the deciding (who may be embedded, from which text, whether a vector is still
fresh); this package only calls them from the unbound worker (``bridge.jobs.embeddings``): ``tables`` wraps the
readers and writers as ``bridge.jobs.reembed.EmbeddingTable``s, ``worker`` runs one pass over both tables and
``policy`` holds the per-run cap.
"""
