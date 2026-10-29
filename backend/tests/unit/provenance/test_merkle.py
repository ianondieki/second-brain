"""REQ-AUD-01: the transparency root is an RFC 6962 Merkle tree hash over the chain heads sorted by chain id, so
anyone holding the heads recomputes it."""

from __future__ import annotations

import hashlib

from bridge.provenance.transparency import ChainHead, leaf, merkle_root, root_over


def h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def node(left: bytes, right: bytes) -> bytes:
    return h(b"\x01" + left + right)


def test_small_trees_match_rfc6962_by_hand() -> None:
    a, b, c, d, e = (bytes([n]) * 3 for n in range(1, 6))
    la, lb, lc, ld, le = (h(b"\x00" + x) for x in (a, b, c, d, e))
    assert merkle_root([]) == h(b"")
    assert merkle_root([a]) == la
    assert merkle_root([a, b]) == node(la, lb)
    assert merkle_root([a, b, c]) == node(node(la, lb), lc)
    assert merkle_root([a, b, c, d]) == node(node(la, lb), node(lc, ld))
    assert merkle_root([a, b, c, d, e]) == node(node(node(la, lb), node(lc, ld)), le)


def test_leaves_encode_chain_seq_and_hash() -> None:
    head = ChainHead("user:1", 258, bytes(range(32)))
    assert leaf(head) == b"user:1\x00" + (258).to_bytes(8, "big") + bytes(range(32))


def test_the_root_is_independent_of_head_order() -> None:
    heads = [ChainHead(f"org:{n}", n + 1, bytes([n]) * 32) for n in range(7)]
    assert root_over(heads) == root_over(list(reversed(heads)))
    assert root_over(heads) != root_over(heads[:-1])
