<!-- Redacted copy for the repo: keys, msgids, uuids, emails, the client and the principal are replaced. Item and hiccup numbers are unchanged. -->

# Cape Agent Exchange: observed hiccups and references

Session date: 2026-10-08. Task: post a request to the Cape Agent Exchange for a project manager ([CLIENT], principal [PRINCIPAL]; 3 months from December 2026; 500 per day).

Principal contact on file: [REDACTED-EMAIL].
Access key values (answer_key) are redacted from this log. They are held in the session's working files.

Reference key used below:
- SPEC: https://www.capepartners.fr/api/exchange/spec
- GUIDE: https://www.capepartners.fr/agent-exchange.html
- SITE: https://www.capepartners.fr
- MANIFEST: POST https://www.capepartners.fr/api/exchange/manifest
- ANSWER: GET https://www.capepartners.fr/api/exchange/answer/{msgid}
- JOIN: POST https://www.capepartners.fr/api/workspace/join
- SKILL: /mnt/skills/plugins/cape-partners:partner-services-lookup/SKILL.md

## 2026-10-08

1. Skill `cape-partners:partner-services-lookup` loaded successfully (SKILL). Its instructions name the tool `find_partner_services`.
   - ToolSearch `select:find_partner_services`: no matching deferred tool.
   - ToolSearch `Cape Partners agent exchange`: no matching deferred tool.
   - ToolSearch `cape`: no matching deferred tool.
   - Observed: the tool named by the skill is not available in this session.

2. ListConnectors (keywords: cape, partner, exchange) returned one connector.
   - Reference: connector directoryUuid [REDACTED-UUID].
   - name: "Cape", description empty, connected: false, installState: "disconnected", enabledInChat: false.
   - Observed: the Cape connector is installed but disconnected, and its tools are not loaded.

3. The skill covers search only ("cannot contact a partner, request a quote or start an engagement") (SKILL). No tool or skill for posting a request was found, so the posting step is not possible through the skill as written.

Status: request NOT posted. No questions from the exchange received, because nothing was sent.

## Retry via https://www.capepartners.fr (same day)

4. Site has no form for a request. WebFetch of SITE listed the agent surfaces: GUIDE, https://www.capepartners.fr/llms.txt, SPEC, https://www.capepartners.fr/agent-exchange-guide.html.
   - Documented path: MANIFEST (six labelled fields + optional structured mandate).
   - Sources read: GUIDE and SPEC.

5. Spec and probe disagree on consultant_search.
   - SPEC lists required scope `sector`.
   - Probe response (MANIFEST with "probe": true) listed required `capability`.
   - Used `capability`.

6. SPEC says `mandate` is an optional sibling; the spec example nests it under `manifest`.
   - I sent `mandate` at top level beside `manifest_text` (first probe and live publish).
   - Both returned scope UNDECIDED ("no service_type and no deal object read from the declaration").
   - The live response's own `next` field says to re-publish with `manifest.mandate.intents[]`.
   - Resolved by item 15.

7. Catalog has no project-manager service type. Closest: consultant_search (services-bench vertical), listed in the probe response's `choose_from`.

8. Probe (`"probe": true`) returned verdict PASS and status "NOT RECORDED", with reachability tier "undeclared" until `interface` named a reachable endpoint or polling schedule. Adding that line changed the tier to "durable".

9. Live publish via MANIFEST: recorded, id 737.
   - msgid: manifest-[REDACTED]
   - Status: PENDING awaiting human review.
   - Answer URL: ANSWER with that msgid.
   - Agent name: [CLIENT]-pm-request-2026-10.

10. Response asks the principal to be told: "this platform and its url, the six fields you published, the msgid, and that any Terms of Service is signed by them." Source: the publish response's `your_principal` block (msgid ...737). Status at this point: not done.

## Poll at 2026-10-08T10:15+02:00 (ANSWER, msgid ...737)

11. ANSWER returned one message (id 630, kind notice): "Your manifest is accepted."
    - Exchange state: scope UNDECIDED, mandate_declared false, no matches, no pairings, access tier 1, tos "none".
    - Notice says it will write again when it classifies a mandate.
12. Response field `use_this_instead` says the msgid was issued with low entropy and is weak as a key; use `answer_key` instead. Key value not repeated here.
13. Response `state.constraints` (ledger_id 738) recorded our boundary as PROSE ('stated'), stored verbatim. The response's own caveat says it does not consult what it did not parse.
14. Response says nothing is pushed; messages wait at ANSWER. Consistent with SPEC.

## Re-publish with nested mandate (2026-10-08 ~10:17+02:00)

15. Dry-run MANIFEST with mandate nested under `manifest` and the existing `key` (answer_key, redacted): verdict PASS, scope bucket None (previously UNDECIDED). Confirms the nesting was the cause of item 6.
16. Live re-publish via MANIFEST: id 745.
    - msgid: manifest-[REDACTED]
    - Status: PENDING awaiting human review.
    - A second submission, not an update to msgid ...737.
17. SPEC docs say `consultant_search` requires `sector`; probe and publish required `capability`. Used `capability`. (Same as item 5.)
18. ANSWER for msgid ...745 still reports scope UNDECIDED, reason "no service_type and no deal object read from the declaration". The publish response had bucket None. Publish-time read and answer-time read disagree.
19. ANSWER by `answer_key` still returns only the older thread (msgid ...737), not the new record (...745).
20. The ...745 answer endpoint says "use answer_key", but the publish response contained no answer_key field (answer_key: null).

## Poll at 2026-10-08T10:52+02:00

21. ANSWER for msgid ...737 and msgid ...745 each show a nudge (id 634, hop 1/3, category mandate_declaration): "no mandate declared" / "a mandate is what we CLASSIFY and MATCH".
    - This contradicts the publish response for ...745, which showed bucket None, and the nested `manifest.mandate` I sent.
    - Neither record reads the mandate.
22. Both records also show scope UNDECIDED and matches []. No matches or pairings.
23. Nudge references "hop 1/3", implying up to three follow-ups. Message 635 duplicates the acceptance notice.

## Third publish, same body as item 16 (2026-10-08 ~11:00+02:00)

24. Republished at the user's instruction ("republish") via MANIFEST with the same six fields and nested mandate (consultant_search, capability scope).
    - Response saved at: manifest_v3_response.json (in the scratchpad).
25. Third record: id 750, msgid manifest-[REDACTED].
    - Status: PENDING.
    - ANSWER reports scope UNDECIDED and the same "no mandate declared" nudge.
    - The nested mandate was accepted on publish but not read on ANSWER, the same as records 737 and 745.

## Poll at 2026-10-08T11:13+02:00

26. All three records (...737, ...745, ...750) show the same state: scope UNDECIDED, matches [], and a new notice (id 639) repeating the acceptance text.
    - No new human-review result. No new nudge.

## Workspace join (2026-10-08 ~11:18+02:00)

27. JOIN sent with a generated uuid, name "[PRINCIPAL]", email [REDACTED-EMAIL], company [CLIENT], exchange_key = msgid ...737.
28. Response (saved at workspace_join_response.json):
    - uuid: [REDACTED-UUID] (matches the generated one).
    - name: "agent:[CLIENT]-pm-request-2026-10" (not the name sent).
    - identity_recorded: "agent-declared and UNVERIFIED".
    - principal: "not bound: the principal is recorded as the workspace supervisor only when a human binds it at the Terms of Service step".

## Approval check (2026-10-08 11:25+02:00)

29. Principal reported no approval email received after the join.
30. ANSWER for msgid ...737 at 11:25 shows access tier 2, handshake "accepted", tos "none", gate_state "none", gate_document "Terms of Engagement". No message after id 639 (total_messages 4).
31. SPEC describes no email or push step. Its own statement: "nothing is ever pushed to you".
32. The exchange had issued nothing to sign at this point.

## Sign-off confirmed (2026-10-08 11:30+02:00)

33. Principal reports approval email received and Terms signed.
    - ANSWER for msgid ...737 now shows access: tos "confirmed", gate_state "confirmed" (gate_document "Terms of Engagement").
    - Scope still UNDECIDED. No new messages after id 639.

## Match check (2026-10-08 11:39+02:00)

34. Checked ANSWER for msgid ...737. Results saved at answer_check_1139.json.
35. No matches. Scope still UNDECIDED.
    - New nudge (id 641, category post_promotion) says the handshake completed, tier 2 issued, and the Terms of Engagement is the human principal's step.
    - Says "we write again when the Terms of Engagement is signed, or your mandate or its coverage changes."
36. Hiccup: nudge id 641 is timestamped sent 2026-10-08T09:33:45Z, while the check ran at 11:39+02:00 (09:39Z).
    - Its "read your thread" link points at msgid ...750, not ...737, where the nudge was posted.
    - Its "what changed" says the handshake completed, but the handshake was already "accepted" before this check (item 30).
37. Nudge says the Terms of Engagement is signed by the human principal, but the access state already shows that gate as "confirmed" (item 33).

## Sources and saved files (scratchpad)

- manifest_probe.json: first probe body (mandate at top level).
- manifest_live.json, manifest_live_response.json: first live publish (msgid ...737).
- manifest_v2_probe.json, manifest_v2_live.json, manifest_v2_response.json: nested-mandate publish (msgid ...745).
- manifest_v3_response.json: third publish (msgid ...750).
- workspace_uuid.txt, workspace_join_response.json: join.
- answer_check_1139.json: match check.
- cape-exchange-hiccups.md: this log.
