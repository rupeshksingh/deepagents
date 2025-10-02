# Defer ChatOpenAI import to avoid Pydantic issues
# from langchain_openai import ChatOpenAI

def get_default_model():
    """Get the default OpenAI chat model."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model_name="gpt-5")
