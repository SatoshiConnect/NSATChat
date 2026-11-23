import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Keypair } from "@stellar/stellar-sdk";
import { buildSignedPayment, paymentPreflight, parsePositiveAmount } from "./transaction.js";

const seed = "SAAACAQDAQCQMBYIBEFAWDANBYHRAEISCMKBKFQXDAMRUGY4DUPB6NKI";
const sender = Keypair.fromSecret(seed);
const destination = "GAYJYVAUMI7BY3UBLV5BSKOWYRH5AR6NUFUO4LXGQEJ7SMAUMKAXI7EQ";
const txHash = "ed416812815ee2993c26ca65ca7e14f8d81f0b0e36ad7aec8b0c32ca0e11b6d7";

describe("NSAT transaction safety", () => {
  it("matches the verified NSAT mainnet transaction hash vector", async () => {
    const preflight = paymentPreflight({
      sourceAddress: sender.publicKey(), destinationAddress: destination, amount: "123456789",
      balance: "999999999999", sequence: "41", baseFee: 10, baseReserve: "100000000", destinationExists: true,
    });
    const signed = await buildSignedPayment({ secret: seed, destinationAddress: destination, preflight });
    const envelope = Uint8Array.from(atob(signed.envelopeXdr), (character) => character.charCodeAt(0));
    assert.equal(signed.hash, txHash);
    assert.equal(signed.sourceAddress, sender.publicKey());
    assert.equal(envelope.length > 200, true);
    assert.equal(sender.verify(Uint8Array.from(signed.hash.match(/../g), (byte) => Number.parseInt(byte, 16)), envelope.slice(-64)), true);
  });

  it("uses exact integer amounts and refuses invalid send states", () => {
    assert.equal(parsePositiveAmount("123,456 789"), 123456789n);
    assert.throws(() => parsePositiveAmount("0"), /amount_out_of_range/);
    assert.throws(() => parsePositiveAmount("1.5"), /amount_whole_number_required/);
    const common = { sourceAddress: sender.publicKey(), destinationAddress: destination, amount: "100", balance: "1000000000", sequence: "42", baseFee: 10, baseReserve: "100000000", destinationExists: true };
    assert.throws(() => paymentPreflight({ ...common, baseFee: 11 }), /fee_policy_unverified/);
    assert.throws(() => paymentPreflight({ ...common, balance: "110" }), /insufficient_balance_or_reserve/);
    assert.throws(() => paymentPreflight({ ...common, destinationAddress: sender.publicKey() }), /self_transfer_not_allowed/);
    assert.throws(() => paymentPreflight({ ...common, destinationExists: false, amount: "100" }), /destination_creation_reserve_too_low/);
  });
});
