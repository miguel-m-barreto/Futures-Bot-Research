from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    MarketDataSourceId,
    ReplayMarketBindingId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketTransportKind,
    QuoteSemantics,
    VenueInstrumentRef,
    VenueMarketKind,
)
from futures_bot.domain.replay import ReplayInputKind, ReplayInstrumentRef
from futures_bot.domain.replay_market_data import (
    ReplayMarketAdapterAuthority,
    ReplayMarketAdapterDescriptor,
    ReplayMarketBindingAuthority,
    ReplayMarketDataBinding,
    ReplayMarketPayloadHashPolicy,
    ReplayMarketTimestampPolicy,
    build_replay_market_adapter_authority,
    build_replay_market_adapter_fingerprint,
    build_replay_market_binding_authority,
    build_replay_market_binding_authority_fingerprint,
    build_replay_market_connection_id,
    build_replay_market_connection_id_from_authority,
    validate_replay_market_connection_id,
    validate_replay_market_data_bindings,
)

SUPPORTED_KINDS = (
    ReplayInputKind.INDEX_PRICE,
    ReplayInputKind.MARK_PRICE,
    ReplayInputKind.ORDER_BOOK_TOP,
    ReplayInputKind.TRADE,
)


def replay_instrument(symbol: str = "BTCUSDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset="BTC",
    )


def source(
    source_id: str = "REPLAY_BINANCE",
    *,
    venue: str | None = "BINANCE",
    kind: MarketDataSourceKind = MarketDataSourceKind.REPLAY,
    provider: str = "replay-fixture",
) -> MarketDataSourceDescriptor:
    return MarketDataSourceDescriptor(
        source_id=MarketDataSourceId(source_id),
        source_kind=kind,
        provider=provider,
        transport=MarketTransportKind.IN_MEMORY,
        venue=None if venue is None else VenueId(value=venue),
        source_version="v1",
    )


def venue_instrument(
    instrument_id: str = "binance-linear-btcusdt",
    *,
    venue: str = "BINANCE",
    raw_symbol: str = "BTCUSDT",
    logical: str = "BTC/USDT",
) -> VenueInstrumentRef:
    return VenueInstrumentRef(
        venue_instrument_id=VenueInstrumentId(instrument_id),
        venue=VenueId(value=venue),
        raw_symbol=raw_symbol,
        logical_instrument=logical,
        market_kind=VenueMarketKind.LINEAR_PERPETUAL,
        settlement_asset="USDT",
        collateral_asset="USDT",
        metadata_version="2026-01",
    )


def binding(  # noqa: PLR0913
    binding_id: str = "binding-1",
    *,
    replay_ref: ReplayInstrumentRef | None = None,
    source_ref: MarketDataSourceDescriptor | None = None,
    venue_ref: VenueInstrumentRef | None = None,
    dataset_id: str = "dataset-1",
    version: str = "v1",
) -> ReplayMarketDataBinding:
    return ReplayMarketDataBinding(
        binding_id=ReplayMarketBindingId(binding_id),
        input_dataset_id=dataset_id,
        replay_instrument=replay_ref or replay_instrument(),
        source=source_ref or source(),
        venue_instrument=venue_ref or venue_instrument(),
        quote_semantics=QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK,
        binding_version=version,
    )


def descriptor(
    *,
    adapter_id: str = "adapter",
    adapter_version: str = "v1",
    kinds: tuple[ReplayInputKind, ...] = SUPPORTED_KINDS,
    timestamp_policy: ReplayMarketTimestampPolicy = (
        ReplayMarketTimestampPolicy.EVENT_TIME_AS_SOURCE_AND_RECEIVED
    ),
    hash_policy: ReplayMarketPayloadHashPolicy = (
        ReplayMarketPayloadHashPolicy.CANONICAL_REPLAY_RECORD
    ),
) -> ReplayMarketAdapterDescriptor:
    return ReplayMarketAdapterDescriptor(
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        supported_input_kinds=kinds,
        timestamp_policy=timestamp_policy,
        payload_hash_policy=hash_policy,
    )


def test_valid_binding_round_trip_and_tampering_revalidation() -> None:
    b = binding()

    assert ReplayMarketDataBinding.model_validate(b.model_dump()) == b

    tampered_source = b.source.model_copy(update={"provider": " replay"})
    with pytest.raises(ValidationError):
        ReplayMarketDataBinding.model_validate(
            b.model_copy(update={"source": tampered_source}).model_dump()
        )


def test_binding_rejects_non_replay_source_raw_symbol_and_asset_conflicts() -> None:
    with pytest.raises(ValidationError):
        binding(source_ref=source(kind=MarketDataSourceKind.DIRECT_VENUE))
    with pytest.raises(ValidationError):
        binding(venue_ref=venue_instrument(raw_symbol="BTC-USDT"))
    with pytest.raises(ValidationError):
        binding(source_ref=source(venue="BINANCE"), venue_ref=venue_instrument(venue="BYBIT"))
    with pytest.raises(ValidationError):
        binding(venue_ref=venue_instrument(logical="BTC/USDC"))


def test_binding_collision_validation_and_order_independent_fingerprint() -> None:
    a = binding("binding-a")
    duplicate = binding("binding-a")
    b = binding(
        "binding-b",
        replay_ref=replay_instrument("ETHUSDT"),
        venue_ref=venue_instrument(
            "binance-linear-ethusdt",
            raw_symbol="ETHUSDT",
            logical="ETH/USDT",
        ),
    )

    assert validate_replay_market_data_bindings((a, duplicate, b)) == (a, b)

    fp_a = build_replay_market_adapter_fingerprint(
        descriptor=descriptor(),
        bindings=(b, a),
    )
    fp_b = build_replay_market_adapter_fingerprint(
        descriptor=descriptor(),
        bindings=(a, b),
    )
    assert fp_a == fp_b
    assert fp_a.startswith("replay-market-adapter:")

    assert fp_a != build_replay_market_adapter_fingerprint(
        descriptor=descriptor(adapter_version="v2"),
        bindings=(a, b),
    )
    assert fp_a != build_replay_market_adapter_fingerprint(
        descriptor=descriptor(),
        bindings=(binding("binding-a", version="v2"), b),
    )


def test_binding_collision_validation_rejects_ambiguous_authority() -> None:
    a = binding("binding-a")
    with pytest.raises(ValueError):
        validate_replay_market_data_bindings(
            (
                a,
                binding("binding-a", replay_ref=replay_instrument("ETHUSDT")),
            )
        )
    with pytest.raises(ValueError):
        validate_replay_market_data_bindings(
            (
                a,
                binding(
                    "binding-b",
                    replay_ref=replay_instrument("ETHUSDT"),
                    source_ref=source(provider="other"),
                ),
            )
        )


def test_adapter_authority_canonicalizes_bindings_and_verifies_fingerprint() -> None:
    a = binding("binding-a")
    duplicate = binding("binding-a")
    b = binding(
        "binding-b",
        replay_ref=replay_instrument("ETHUSDT"),
        venue_ref=venue_instrument(
            "binance-linear-ethusdt",
            raw_symbol="ETHUSDT",
            logical="ETH/USDT",
        ),
    )

    authority = build_replay_market_adapter_authority(
        descriptor=descriptor(),
        bindings=(b, a, duplicate),
    )
    reordered = build_replay_market_adapter_authority(
        descriptor=descriptor(),
        bindings=(a, b),
    )

    assert authority == ReplayMarketAdapterAuthority.model_validate(authority.model_dump())
    assert authority.bindings == (a, b)
    assert authority == reordered
    assert authority.adapter_fingerprint == build_replay_market_adapter_fingerprint(
        descriptor=descriptor(),
        bindings=(a, b),
    )

    with pytest.raises(ValidationError):
        ReplayMarketAdapterAuthority.model_validate(
            authority.model_copy(
                update={"adapter_fingerprint": "replay-market-adapter:" + "0" * 64}
            )
        )


def test_adapter_authority_rejects_empty_conflicting_or_stale_fingerprint() -> None:
    a = binding("binding-a")
    b = binding(
        "binding-b",
        replay_ref=replay_instrument("ETHUSDT"),
        venue_ref=venue_instrument(
            "binance-linear-ethusdt",
            raw_symbol="ETHUSDT",
            logical="ETH/USDT",
        ),
    )
    authority = build_replay_market_adapter_authority(
        descriptor=descriptor(),
        bindings=(a, b),
    )

    with pytest.raises(ValidationError):
        ReplayMarketAdapterAuthority(
            descriptor=descriptor(),
            bindings=(),
            adapter_fingerprint="replay-market-adapter:" + "0" * 64,
        )
    with pytest.raises(ValueError):
        build_replay_market_adapter_authority(
            descriptor=descriptor(),
            bindings=(a, binding("binding-a", replay_ref=replay_instrument("ETHUSDT"))),
        )
    with pytest.raises(ValidationError):
        ReplayMarketAdapterAuthority(
            descriptor=descriptor(adapter_version="v2"),
            bindings=authority.bindings,
            adapter_fingerprint=authority.adapter_fingerprint,
        )
    with pytest.raises(ValidationError):
        ReplayMarketAdapterAuthority(
            descriptor=authority.descriptor,
            bindings=(authority.bindings[0].model_copy(update={"binding_version": "v2"}), b),
            adapter_fingerprint=authority.adapter_fingerprint,
        )
    with pytest.raises(ValidationError):
        ReplayMarketAdapterAuthority(
            descriptor=authority.descriptor,
            bindings=(a,),
            adapter_fingerprint=authority.adapter_fingerprint,
        )
    with pytest.raises(ValidationError):
        ReplayMarketAdapterAuthority(
            descriptor=authority.descriptor,
            bindings=(a, b, binding("binding-c", replay_ref=replay_instrument("LTCUSDT"))),
            adapter_fingerprint=authority.adapter_fingerprint,
        )


def test_binding_authority_round_trip_deterministic_fingerprint_and_tampering() -> None:
    b = binding()
    desc = descriptor()
    authority = build_replay_market_binding_authority(descriptor=desc, binding=b)

    assert ReplayMarketBindingAuthority.model_validate(authority.model_dump()) == authority
    assert build_replay_market_binding_authority(descriptor=desc, binding=b) == authority
    assert authority.binding_authority_fingerprint == (
        build_replay_market_binding_authority_fingerprint(descriptor=desc, binding=b)
    )
    assert authority.binding_authority_fingerprint.startswith(
        "replay-market-binding-authority:"
    )

    with pytest.raises(ValidationError):
        ReplayMarketBindingAuthority.model_validate(
            authority.model_copy(
                update={
                    "binding_authority_fingerprint": (
                        "replay-market-binding-authority:" + "0" * 64
                    )
                }
            ).model_dump()
        )
    with pytest.raises(ValidationError):
        ReplayMarketBindingAuthority(
            descriptor=desc,
            binding=b,
            binding_authority_fingerprint="not-a-binding-authority",
        )


def test_binding_authority_rejects_stale_descriptor_fingerprint() -> None:
    b = binding()
    desc = descriptor()
    authority = build_replay_market_binding_authority(descriptor=desc, binding=b)
    descriptor_mutations = (
        descriptor(adapter_id="adapter-v2"),
        descriptor(adapter_version="v2"),
        descriptor(kinds=(ReplayInputKind.INDEX_PRICE, ReplayInputKind.TRADE)),
        descriptor(hash_policy=ReplayMarketPayloadHashPolicy.REQUIRE_SUPPLIED_SHA256),
    )

    for changed_descriptor in descriptor_mutations:
        assert changed_descriptor != desc
        assert build_replay_market_binding_authority_fingerprint(
            descriptor=changed_descriptor,
            binding=b,
        ) != authority.binding_authority_fingerprint
        with pytest.raises(ValidationError):
            ReplayMarketBindingAuthority(
                descriptor=changed_descriptor,
                binding=b,
                binding_authority_fingerprint=authority.binding_authority_fingerprint,
            )

    invalid_descriptor = desc.model_dump()
    invalid_descriptor["timestamp_policy"] = "UNSUPPORTED_TIMESTAMP_POLICY"
    with pytest.raises(ValidationError):
        ReplayMarketBindingAuthority(
            descriptor=invalid_descriptor,  # type: ignore[arg-type]
            binding=b,
            binding_authority_fingerprint=authority.binding_authority_fingerprint,
        )


def test_binding_authority_rejects_stale_binding_fingerprint() -> None:
    b = binding()
    desc = descriptor()
    authority = build_replay_market_binding_authority(descriptor=desc, binding=b)
    eth_replay = replay_instrument("ETHUSDT")
    binding_mutations = (
        b.model_copy(update={"binding_id": ReplayMarketBindingId("binding-other")}),
        b.model_copy(update={"input_dataset_id": "dataset-other"}),
        binding(
            replay_ref=eth_replay,
            venue_ref=venue_instrument(
                "binance-linear-ethusdt",
                raw_symbol="ETHUSDT",
                logical="ETH/USDT",
            ),
        ),
        b.model_copy(update={"source": b.source.model_copy(update={"provider": "other"})}),
        b.model_copy(
            update={
                "venue_instrument": b.venue_instrument.model_copy(
                    update={"metadata_version": "2026-02"}
                )
            }
        ),
        b.model_copy(update={"quote_semantics": QuoteSemantics.INDICATIVE}),
        b.model_copy(update={"binding_version": "v2"}),
    )

    for changed_binding in binding_mutations:
        assert changed_binding != b
        assert build_replay_market_binding_authority_fingerprint(
            descriptor=desc,
            binding=changed_binding,
        ) != authority.binding_authority_fingerprint
        with pytest.raises(ValidationError):
            ReplayMarketBindingAuthority(
                descriptor=desc,
                binding=changed_binding,
                binding_authority_fingerprint=authority.binding_authority_fingerprint,
            )


def test_adapter_descriptor_rejects_unsorted_duplicate_or_unsupported_kinds() -> None:
    with pytest.raises(ValidationError):
        descriptor(kinds=(ReplayInputKind.TRADE, ReplayInputKind.MARK_PRICE))
    with pytest.raises(ValidationError):
        descriptor(kinds=(ReplayInputKind.TRADE, ReplayInputKind.TRADE))
    with pytest.raises(ValidationError):
        descriptor(kinds=(ReplayInputKind.OHLCV_BAR,))


def test_no_real_clock_is_needed_for_binding_identities() -> None:
    assert datetime(2026, 1, 1, tzinfo=UTC).tzinfo is UTC


def test_replay_market_connection_id_uses_only_declared_authority_fields() -> None:
    b = binding()
    authority = build_replay_market_binding_authority(descriptor=descriptor(), binding=b)

    from_binding = build_replay_market_connection_id(
        input_dataset_id=b.input_dataset_id,
        binding_authority=authority,
    )
    from_authority = build_replay_market_connection_id_from_authority(
        input_dataset_id=b.input_dataset_id,
        binding_authority_fingerprint=authority.binding_authority_fingerprint,
        binding_id=b.binding_id,
        source_id=b.source.source_id,
        venue_instrument_id=b.venue_instrument.venue_instrument_id,
    )

    assert from_binding == from_authority
    assert from_authority == build_replay_market_connection_id_from_authority(
        input_dataset_id=b.input_dataset_id,
        binding_authority_fingerprint=authority.binding_authority_fingerprint,
        binding_id=b.binding_id,
        source_id=b.source.source_id,
        venue_instrument_id=b.venue_instrument.venue_instrument_id,
    )
    assert validate_replay_market_connection_id(
        type(from_authority).model_validate(from_authority.model_dump())
    ) == from_authority

    assert from_authority != build_replay_market_connection_id_from_authority(
        input_dataset_id="dataset-other",
        binding_authority_fingerprint=authority.binding_authority_fingerprint,
        binding_id=b.binding_id,
        source_id=b.source.source_id,
        venue_instrument_id=b.venue_instrument.venue_instrument_id,
    )
    assert from_authority != build_replay_market_connection_id_from_authority(
        input_dataset_id=b.input_dataset_id,
        binding_authority_fingerprint=authority.binding_authority_fingerprint,
        binding_id=ReplayMarketBindingId("binding-other"),
        source_id=b.source.source_id,
        venue_instrument_id=b.venue_instrument.venue_instrument_id,
    )
    assert from_authority != build_replay_market_connection_id_from_authority(
        input_dataset_id=b.input_dataset_id,
        binding_authority_fingerprint=authority.binding_authority_fingerprint,
        binding_id=b.binding_id,
        source_id=MarketDataSourceId("REPLAY_OTHER"),
        venue_instrument_id=b.venue_instrument.venue_instrument_id,
    )
    assert from_authority != build_replay_market_connection_id_from_authority(
        input_dataset_id=b.input_dataset_id,
        binding_authority_fingerprint=authority.binding_authority_fingerprint,
        binding_id=b.binding_id,
        source_id=b.source.source_id,
        venue_instrument_id=VenueInstrumentId("other-instrument"),
    )
    assert from_authority != build_replay_market_connection_id_from_authority(
        input_dataset_id=b.input_dataset_id,
        binding_authority_fingerprint="replay-market-binding-authority:" + "0" * 64,
        binding_id=b.binding_id,
        source_id=b.source.source_id,
        venue_instrument_id=b.venue_instrument.venue_instrument_id,
    )

    with pytest.raises(ValueError):
        validate_replay_market_connection_id(type(from_authority)(value="not-replay"))
    with pytest.raises(ValueError):
        validate_replay_market_connection_id(
            from_authority.model_copy(update={"value": "not-replay"})
        )
