from ca3.attack_knowledge import AttackTechnique, retrieve_techniques


def test_attack_retrieval_prioritizes_public_facing_exploit() -> None:
    techniques = [
        AttackTechnique(
            "T1190",
            "Exploit Public-Facing Application",
            ("initial-access",),
            "Exploit an Internet-facing host to initially access a network.",
            "attack-pattern--one",
            "2026-01-01T00:00:00Z",
        ),
        AttackTechnique(
            "T1003",
            "OS Credential Dumping",
            ("credential-access",),
            "Dump credentials from an operating system.",
            "attack-pattern--two",
            "2026-01-01T00:00:00Z",
        ),
    ]
    ranked = retrieve_techniques(
        "exploit public-facing web server for initial access", techniques, top_k=2
    )
    assert ranked[0][0].technique_id == "T1190"
    assert ranked[0][1] > ranked[1][1]
