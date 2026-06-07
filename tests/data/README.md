# Test data

All bundled fixtures in this folder are in the **public domain** so the test suite has no
licensing strings attached.

| File | Source | License |
|------|--------|---------|
| `us_constitution_preamble.txt` | US federal government, 1787 | Public domain (US federal works are PD by 17 USC §105) |
| `shakespeare_sonnet18.txt`     | William Shakespeare, c. 1609 | Public domain (life+70: died 1616) |
| `poe_raven_stanza1.txt`        | Edgar Allan Poe, 1845 | Public domain (life+70: died 1849) |
| `gutenberg_alice_chapter1.txt` | Lewis Carroll, *Alice's Adventures in Wonderland*, 1865, Project Gutenberg #11 | Public domain (life+70: died 1898) |

For testing on real Wikipedia content (CC BY-SA 4.0), run:

```bash
./fetch_test_data.sh
```

which downloads a few Wikipedia articles into this folder. The tests pick up whatever
fixtures are present, so the offline PD set is enough to exercise the full pipeline.
