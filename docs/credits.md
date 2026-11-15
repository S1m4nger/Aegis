# Credits and provenance

## Dataset
- PaySim: https://www.kaggle.com/datasets/ealaxi/paysim1 — public, synthetic financial transaction simulation. Source file uploaded by participant. Respect official dataset limitations and licence.
- Main competition: https://highschoolhackathon.org/briefs

## Libraries / frameworks actually used
- Uber Fx: https://github.com/uber-go/fx (DI/lifecycle)
- Uber Zap: https://github.com/uber-go/zap (structured logging)
- chi: https://github.com/go-chi/chi (HTTP router)
- scikit-learn: https://scikit-learn.org/ (ML)
- pandas: https://pandas.pydata.org/ (data)
- FastAPI: https://fastapi.tiangolo.com/ (internal scoring)
- Streamlit: https://streamlit.io/ (demo UI)
- Graphify: https://www.graphiffy.com/ (local code graph extraction and traversal, actually used)

## AI development assistants — explicit disclosure mandatory
- ChatGPT (architecture and starter kit assistance): https://chatgpt.com/
- OpenAI Codex (code generation and review): https://openai.com/codex/ — used for implementation, review and verification.
- No other AI generation tools were used in this implementation session.

## Authorship
Solo participant. No Co-authored-by or fictitious teammate credit; **this is distinct from mandatory disclosure of AI tooling**. Do not falsely claim the entire implementation was manually typed or developed without assistance. Keep copyright/licenses of dependencies intact. Git commits should use the real participant's own configured identity, not a fictitious identity.

## External examples / tutorials
Implementation adapted from the participant-provided, AI-assisted starter. No other implementation/tutorial code was copied; official documentation was used to verify APIs. Exact reference URLs and version limitations are in `docs/dependency-notes.md`.

## Actual implementation session
OpenAI Codex used for implementation, temporary tests, code review and documentation; ChatGPT supplied the original starter. Parallel Codex agents assist as AI tools, not human teammates or authors. Graphify existing local CLI used for code AST extraction/queries. Context7 used for library documentation lookup. No additional AI tools used in this session.

## Additional direct dependencies and verification tools
- NumPy: https://numpy.org/ — numerical arrays and transforms.
- Joblib: https://joblib.readthedocs.io/ — trusted local model artifact serialization.
- Pydantic: https://docs.pydantic.dev/ — inference request validation.
- Uvicorn: https://www.uvicorn.org/ — local ASGI server.
- Plotly: https://plotly.com/python/ — interactive evidence figures.
- pytest: https://docs.pytest.org/ — temporary regression suites.
- threadpoolctl: https://github.com/joblib/threadpoolctl — bounded numerical worker threads.
- Context7: https://context7.com/ — documentation lookup; documentation sources cited in dependency-notes.md.
Exact transitive dependencies are retained in the Python lock file and Go go.sum; original dependency licenses remain applicable. No pretrained external model was used: Logistic Regression and calibration were fitted locally on the declared PaySim windows.
