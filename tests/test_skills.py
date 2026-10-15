from jobot.skills import SKILLS, category_of, extract_skills


def test_finds_skills_under_their_spellings():
    text = ("PLC (Siemens TIA Portal) and SCADA; ETAP load flow; 11kV switchgear; C++ / embedded C on ESP32; "
            "CCNA; ISO 9001; PVsyst solar design; valid driving license")
    assert extract_skills(text) == [
        "C / C++", "ETAP", "PVsyst / HOMER", "Power systems analysis", "Switchgear & substations", "HV / MV / LV",
        "Solar PV", "PLC", "SCADA / HMI", "Siemens", "Embedded systems", "ARM / STM32 / ESP32", "Networking (CCNA)",
        "Quality / Lean",
        "Driving licence"]


def test_everyday_words_are_not_skills():
    assert extract_skills("They ran a meeting, sat down, ate lunch and lifted the box. Hart is fat; lean on me.") == []
    assert extract_skills("") == []


def test_extra_skills_and_categories():
    assert extract_skills("We use Ignition Edge daily", extra=["Ignition Edge", "Nothing"]) == ["SCADA / HMI", "Ignition Edge"]
    assert category_of("PLC") == "Control & automation" and category_of("Ignition Edge") == "Other"
    assert len(SKILLS) > 60 and all(aliases for _, aliases in SKILLS.values())
