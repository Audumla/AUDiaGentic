# local-openai

## Purpose

HTTP OpenAI-compatible endpoint used heavily in MVP for deterministic and low-cost stages.

## Canonical id
- `local-openai`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
