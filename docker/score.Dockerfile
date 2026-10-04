# Scoring: no API key. zurix is pinned to the public 0.3.0 release commit.
FROM python:3.12-bookworm@sha256:e91fec3d1ac69f04e4eddcd29c327e630ce34658cf31075bfa7e8b0e052bafea

COPY --from=node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ARG ZURIX_COMMIT=23b8b3f6682b98b1b47fdf31a54868fe46e07e89
RUN pip install --no-cache-dir "zurixai @ git+https://github.com/HuziM/zurixai@${ZURIX_COMMIT}"

RUN useradd --create-home --shell /bin/bash scorer
USER scorer
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /home/scorer
COPY --chown=scorer:scorer score_in_container.py /usr/local/bin/score_in_container.py
ENTRYPOINT ["python", "/usr/local/bin/score_in_container.py"]
