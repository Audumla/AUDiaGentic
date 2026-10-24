variable "CI_CACHE_WRITE" { default = "false" }

target "base" {
  context = "."
  dockerfile = "tests/docker/Dockerfile.test-base"
  cache-from = ["type=gha,scope=test-base"]
  cache-to = CI_CACHE_WRITE == "true" ? ["type=gha,scope=test-base,mode=max"] : []
}

target "suite" {
  context = "."
  dockerfile = "tests/docker/Dockerfile.test"
  contexts = { audia-test-base = "target:base" }
  args = { CI_BROWSER_ASSETS = "0" }
  tags = ["audiagentic-test:ci"]
  output = ["type=docker"]
  cache-from = ["type=gha,scope=ci-suite"]
  cache-to = CI_CACHE_WRITE == "true" ? ["type=gha,scope=ci-suite,mode=max"] : []
}
