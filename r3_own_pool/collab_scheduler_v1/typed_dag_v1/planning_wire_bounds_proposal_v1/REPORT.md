# Optional bounded planning wire proposal — zero calls

Current Goal IR/producer Schema strings use minLength but do not bound refs/symbols. Real scanner B repeated its ref until output truncation. Added planning_wire_bounds.py bounded_schema(): deep-copy transformation, opt-in, limits refs/symbols48 chars, units24, names80 and description/subtask240. Producer refs receive the same48 cap. Candidate strings are rejected, never shortened or repaired. No generated ID, inferred producer, deleted edge or fixed topology. Original generator/default Schema untouched and historical freezes unchanged.

Seven tests added: immutability, legal three/five-node examples in both representations, long refs/symbols/producer refs rejection and variable count retained. 342 typed+18 fixed=360 tests passed. Independent generic fixture plans only; exposed real tasks not used for Prompt tuning. This is a wire-bound proposal, not real success evidence.

Backend check uses original to_service_schema (uniqueItems removed for transport only) then installed vLLM pure precheck/xgrammar compile. Raw A Schema predictably rejected due existing uniqueItems; it is not the wire limit failure. Converted results are saved in BACKEND_PRECHECK.json. No inference/HTTP/service.

Length caps can bound one repeated string but do not prevent repetitions across legal fields or ensure exact symbol correspondence. Field verbosity and required facts/expression relationships still need semantically correct planning. Hard input/output Token limits remain authoritative: bounded strings do not prove a five-node graph fits768 Tokens. No output cap increase proposed without fresh complete Tokenizer envelope for both arms. Reducing duplicate type/unit declarations would require a reviewed optional protocol/compiler change; not implemented here.

Before any use, explicitly select this protocol, inspect legal identifier compatibility, measure full Prompt/Schema and worst review envelope, freeze a new version and obtain a fresh real-call budget. No authorized runner uses this proposal automatically; no additional real request was sent. No commits/push. Stop after preparation.
