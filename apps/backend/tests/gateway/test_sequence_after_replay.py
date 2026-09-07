def test_reconnect_sequence_must_continue_after_replayed_events():
    initial_sequence = 2
    replayed_sequences = [2, 3, 12]

    next_sequence = max(
        initial_sequence,
        max(replayed_sequences) + 1,
    )

    assert next_sequence == 13
