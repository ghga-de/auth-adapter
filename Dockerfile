# Copyright 2021 - 2024 Universität Tübingen, DKFZ, EMBL, and Universität zu Köln
# for the German Human Genome-Phenome Archive (GHGA)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# BASE: a base image with updated packages
FROM python:3.12-alpine AS base
RUN apk upgrade --no-cache --available

# BUILDER: a container to build the service wheel
FROM base AS builder
RUN pip install build
COPY . /service
WORKDIR /service
RUN python -m build

# DEP-BUILDER: a container to (build and) install dependencies
FROM base AS dep-builder
RUN apk update
RUN apk add build-base gcc g++ libffi-dev zlib-dev gdb
RUN apk upgrade --available
WORKDIR /service
COPY --from=builder /service/lock/requirements.txt /service
RUN pip install --no-deps -r requirements.txt
RUN pip install debugpy

# RUNNER: a container to run the service
FROM base AS runner
WORKDIR /service
RUN rm -rf /usr/local/lib/python3.12
COPY --from=dep-builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /service/dist/ /service
RUN pip install --no-deps *.whl
RUN rm *.whl
RUN adduser -D appuser
WORKDIR /home/appuser
USER appuser
ENV PYTHONUNBUFFERED=1

# run auth service
ENTRYPOINT ["auth-service"]
