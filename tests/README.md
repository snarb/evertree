# Tests

```sh
uv run pytest -q
uv run ruff check src tests
```

Тесты самого EverTree используют pytest. Они работают без LLM; на Windows включают настоящую изоляцию AppContainer. Живые SDK-проверки включаются отдельно через `EVERTREE_CODEX_INTEGRATION=1`.

Для тестов создаваемых агентом Programs действует отдельный контракт: committed `tests/test_*.py` с `unittest.TestCase`. Core запускает их в sandbox перед принятием кандидата; этот каталог не является набором тестов ядра EverTree.
