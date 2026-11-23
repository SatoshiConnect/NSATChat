# Test Results

## Baseline before refactor

Captured on the clean `feature/seamless-nsat-wallet` starting point before architecture edits:

- Backend Django suite: 396 discovered; 395 passed, 1 failed, 1 skipped. The one failure is the pre-existing `AssistantTests.test_rejected_key_message`, which expects the literal word “rejected” while the current safe error response says the server key was not accepted. This branch does not change that message.
- Frontend security tests: 10/10 passed.
- ESLint: passed.
- Vite production build: passed, with the existing advisory that a generated chunk exceeds 500 kB.

## After refactor

- Backend Django suite: 401 discovered; 400 passed, 0 failed, 1 skipped. The baseline failure was an outdated test expectation for the wording of the safe Gemini key error; the test now asserts the current wording without changing runtime behavior.
- Frontend security tests: 10/10 passed.
- ESLint: passed.
- Vite production build: passed; Wallet remains lazy-loaded into a separate `wallet-*.js` chunk. The existing >500 kB advisory remains.
- Python syntax compilation and `git diff --check`: passed.
- Focused regression set after the final policy/flag changes: 22 tests discovered, 21 passed and 1 existing skipped; includes architecture boundaries, Wallet canonical/legacy/disabled behavior, Status, and the assistant status endpoint.

Physical iOS/Android devices, production OAuth consent, live calling, and external Wallet services are not represented by these automated tests.
