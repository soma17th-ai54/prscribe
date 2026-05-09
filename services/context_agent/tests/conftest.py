import os

# Provide a dummy API key so get_solar_pro() doesn't raise KeyError during tests.
# The actual model is mocked via patch("context_agent.agent.create_react_agent").
os.environ.setdefault("SOLAR_API_KEY", "test-dummy-key-for-unit-tests")
