from pr_agent.git_providers.local_git_provider import LocalGitProvider


def _provider_with_description(description: str) -> LocalGitProvider:
    provider = object.__new__(LocalGitProvider)  # bypass heavy __init__
    provider.get_pr_description_full = lambda: description
    return provider


def test_user_description_clipped_before_localized_type_header():
    """#pr-type-vi: the 'Type' header is localized to 'Loại PR' in pr_description.py,
    so the boundary list in _possible_headers() must know that spelling too -
    otherwise get_user_description() bleeds the 'Loại PR' section (and everything
    after it) into the extracted user text, which then gets re-embedded as a
    duplicate 'Loại PR' section on the next /describe run."""
    description = (
        "### **User description**\n"
        "original user text\n"
        "___\n"
        "### **Loại PR**\n"
        "Bug fix\n"
        "___\n"
        "### **Description**\n"
        "AI summary\n"
    )
    provider = _provider_with_description(description)

    user_description = provider.get_user_description()

    assert user_description == "original user text"
    assert "Loại PR" not in user_description


if __name__ == "__main__":
    test_user_description_clipped_before_localized_type_header()
    print("ok")
