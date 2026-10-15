"""A lexicon of EEE skills, tools and certificates, found in adverts and resumes.

Spotting skills with plain keyword rules (no AI) gives the dashboard hard
numbers – which skills employers ask for, and which of them your resume
shows – and works offline. Each skill has a category and the spellings it
appears under; matching follows the config's keyword rules (whole words,
case-insensitive, a trailing * is a wildcard).
"""

from __future__ import annotations

from functools import lru_cache

from .filters import keyword_pattern

# canonical name -> (category, spellings that count)
SKILLS: dict[str, tuple[str, list[str]]] = {
    # -- programming & analysis
    "Python": ("Programming", ["python"]),
    "C / C++": ("Programming", ["c++", "c/c++", "c programming", "embedded c", "c language"]),
    "MATLAB / Simulink": ("Programming", ["matlab", "simulink"]),
    "LabVIEW": ("Programming", ["labview"]),
    "Java / JavaScript": ("Programming", ["java", "javascript", "node.js"]),
    "SQL / databases": ("Programming", ["sql", "mysql", "postgresql", "database*"]),
    "Verilog / VHDL": ("Programming", ["verilog", "vhdl", "systemverilog"]),
    "Linux": ("Programming", ["linux", "ubuntu server"]),
    "Excel / data analysis": ("Programming", ["excel", "power bi", "data analysis", "data analytics"]),
    # -- design & simulation tools
    "AutoCAD": ("Design tools", ["autocad", "auto cad"]),
    "Revit / BIM": ("Design tools", ["revit", "bim"]),
    "SolidWorks / CAD": ("Design tools", ["solidworks", "fusion 360", "inventor", "catia"]),
    "EPLAN": ("Design tools", ["eplan"]),
    "ETAP": ("Design tools", ["etap"]),
    "DIgSILENT": ("Design tools", ["digsilent", "powerfactory"]),
    "PSS/E · PSCAD": ("Design tools", ["pss/e", "pscad", "pss e"]),
    "Altium / Eagle": ("Design tools", ["altium", "eagle cad", "orcad"]),
    "KiCad": ("Design tools", ["kicad"]),
    "Proteus / Multisim": ("Design tools", ["proteus", "multisim", "ltspice", "spice simulation"]),
    "DIALux / Relux": ("Design tools", ["dialux", "relux"]),
    "PVsyst / HOMER": ("Design tools", ["pvsyst", "homer", "helioscope", "sketchup"]),
    # -- power systems
    "Power systems analysis": ("Power", ["power system*", "load flow", "short circuit", "fault analysis",
                                         "power flow", "stability study", "stability studies"]),
    "Protection & relays": ("Power", ["protection relay*", "relay setting*", "protection system*",
                                      "protection scheme*", "protection and control", "scada protection"]),
    "Switchgear & substations": ("Power", ["switchgear", "substation*", "circuit breaker*", "ring main unit*",
                                           "gas insulated switchgear", "rmu"]),
    "Transformers": ("Power", ["transformer*"]),
    "HV / MV / LV": ("Power", ["high voltage", "medium voltage", "low voltage", "hv", "mv", "lv", "33kv", "11kv",
                               "132kv", "220kv"]),
    "Earthing & lightning protection": ("Power", ["earthing", "grounding", "lightning protection"]),
    "Power quality & metering": ("Power", ["power quality", "harmonic*", "energy meter*", "smart meter*",
                                           "metering", "power factor correction"]),
    "Generators & UPS": ("Power", ["generator*", "ups", "genset*", "diesel generator*", "battery bank*"]),
    "Energy audit & efficiency": ("Power", ["energy audit*", "energy efficiency", "energy management",
                                            "energy saving"]),
    "Cable sizing & LV design": ("Power", ["cable sizing", "cable calculation*", "lv design", "load calculation*",
                                           "electrical design", "single line diagram*", "sld"]),
    # -- renewables & EV
    "Solar PV": ("Renewables & EV", ["solar", "photovoltaic*", "pv system*", "rooftop solar", "inverter*"]),
    "Wind & hydro": ("Renewables & EV", ["wind turbine*", "wind power", "mini hydro", "hydropower", "hydro power"]),
    "Battery storage / BMS": ("Renewables & EV", ["battery storage", "bess", "energy storage", "lithium",
                                                  "battery management"]),
    "EV charging": ("Renewables & EV", ["ev charg*", "electric vehicle*", "charging station*", "ocpp"]),
    "Microgrids": ("Renewables & EV", ["microgrid*", "mini grid*", "hybrid system*"]),
    # -- control & automation
    "PLC": ("Control & automation", ["plc", "plcs", "programmable logic controller*", "ladder logic"]),
    "SCADA / HMI": ("Control & automation", ["scada", "hmi", "dcs", "wincc", "ignition", "citect", "intouch"]),
    "Siemens": ("Control & automation", ["siemens", "tia portal", "step 7", "s7-1200", "s7-1500", "s7-300"]),
    "Allen-Bradley / Rockwell": ("Control & automation", ["allen-bradley", "allen bradley", "rockwell", "studio 5000"]),
    "Schneider / ABB / Mitsubishi": ("Control & automation", ["schneider", "abb", "mitsubishi", "omron",
                                                              "delta plc", "fanuc"]),
    "Industrial protocols": ("Control & automation", ["modbus", "profibus", "profinet", "opc ua", "opc-ua", "bacnet",
                                                      "canbus", "can bus", "ethernet/ip"]),
    "Drives & motors": ("Control & automation", ["vfd*", "variable frequency drive*", "motor drive*", "servo*",
                                                 "soft starter*", "induction motor*", "motor control"]),
    "Control theory (PID)": ("Control & automation", ["pid", "control system*", "control theory", "control loop*"]),
    "Instrumentation": ("Control & automation", ["instrumentation", "sensors", "transmitter*", "calibration"]),
    "Robotics & mechatronics": ("Control & automation", ["robotic*", "mechatronic*", "cobot*"]),
    # -- electronics & embedded
    "PCB design": ("Electronics & embedded", ["pcb", "pcb design", "pcb layout", "schematic capture",
                                              "circuit design", "schematic*"]),
    "Embedded systems": ("Electronics & embedded", ["embedded", "firmware", "microcontroller*", "mcu", "bare metal"]),
    "ARM / STM32 / ESP32": ("Electronics & embedded", ["arm cortex", "stm32", "esp32", "esp8266", "pic microcontroller*",
                                                       "avr", "nrf52", "atmega"]),
    "Arduino / Raspberry Pi": ("Electronics & embedded", ["arduino", "raspberry pi", "beaglebone", "jetson"]),
    "RTOS": ("Electronics & embedded", ["rtos", "freertos", "zephyr", "real-time operating system*"]),
    "FPGA / DSP": ("Electronics & embedded", ["fpga", "dsp", "xilinx", "vivado", "quartus", "digital signal processing"]),
    "Analog / mixed-signal": ("Electronics & embedded", ["analog design", "analogue design", "analog circuit*",
                                                         "op-amp*", "adc", "mixed-signal", "mixed signal"]),
    "Power electronics": ("Electronics & embedded", ["power electronics", "smps", "dc-dc", "dc/dc", "inverter design",
                                                     "motor driver*", "buck converter*", "boost converter*"]),
    "IoT": ("Electronics & embedded", ["iot", "internet of things", "mqtt", "lora", "lorawan", "zigbee", "nb-iot",
                                       "thingsboard", "node-red"]),
    "Wireless / RF": ("Electronics & embedded", ["rf design", "rf engineer*", "antenna*", "bluetooth", "bluetooth low energy",
                                                  "wi-fi", "wifi", "rfid", "nfc"]),
    "EMC / testing & validation": ("Electronics & embedded", ["emc", "emi", "environmental testing", "hardware testing",
                                                              "hardware validation", "test fixture*"]),
    "Machine learning / AI": ("Electronics & embedded", ["machine learning", "deep learning", "tensorflow", "tinyml",
                                                         "computer vision", "opencv", "pytorch"]),
    # -- telecom & networks
    "Networking (CCNA)": ("Telecom & networks", ["ccna", "ccnp", "cisco", "routing and switching", "tcp/ip", "lan/wan",
                                                 "network administration", "mikrotik"]),
    "Fibre & FTTH": ("Telecom & networks", ["fiber", "fibre", "ftth", "gpon", "otdr", "splicing", "optical network*"]),
    "Mobile networks (4G / 5G)": ("Telecom & networks", ["lte", "4g", "5g", "gsm", "umts", "radio access network*", "drive test*",
                                                         "rf planning", "bts", "node b"]),
    "Microwave / transmission": ("Telecom & networks", ["microwave link*", "transmission network*", "sdh", "dwdm",
                                                        "mpls", "vsat", "satellite"]),
    "Vendor gear (Huawei / ZTE / Ericsson / Nokia)": ("Telecom & networks", ["huawei", "zte", "ericsson", "nokia",
                                                                              "juniper"]),
    "VoIP & unified comms": ("Telecom & networks", ["voip", "sip trunk*", "asterisk", "pbx", "unified communication*"]),
    "Network security": ("Telecom & networks", ["firewall*", "fortinet", "palo alto", "network security", "vpn",
                                                "cybersecurity", "cyber security"]),
    # -- building services
    "MEP design & supervision": ("Building services", ["mep", "building services", "electrical services",
                                                       "mechanical and electrical"]),
    "HVAC": ("Building services", ["hvac", "air conditioning", "chiller*", "vrf", "ventilation"]),
    "Fire alarm & detection": ("Building services", ["fire alarm*", "fire detection", "fire fighting",
                                                     "fire protection", "addressable"]),
    "BMS / building automation": ("Building services", ["bms", "building management system*", "building automation",
                                                        "ddc"]),
    "CCTV & access control": ("Building services", ["cctv", "access control", "security system*", "intruder alarm*",
                                                    "surveillance", "elv"]),
    "Lighting design": ("Building services", ["lighting design", "led lighting", "street light*", "lux level*"]),
    "Structured cabling": ("Building services", ["structured cabling", "cat6", "cat 6", "cabling"]),
    "Lifts & escalators": ("Building services", ["lift", "lifts", "elevator*", "escalator*"]),
    # -- professional
    "Project management": ("Professional", ["project management", "project manager", "pmp", "prince2", "ms project",
                                            "primavera", "project planning", "gantt"]),
    "Estimation, BOQ & tendering": ("Professional", ["boq", "bill of quantities", "estimation", "estimating",
                                                     "tender*", "costing", "quotation*"]),
    "Testing & commissioning": ("Professional", ["commissioning", "testing and commissioning", "factory acceptance",
                                                 "site acceptance"]),
    "Maintenance & troubleshooting": ("Professional", ["preventive maintenance", "predictive maintenance",
                                                       "breakdown maintenance", "troubleshooting", "fault finding",
                                                       "root cause analysis", "maintenance planning"]),
    "Site supervision": ("Professional", ["site supervision", "site management", "installation supervision",
                                          "contractor management", "site coordination"]),
    "Safety & standards": ("Professional", ["osha", "iso 45001", "hse", "health and safety", "risk assessment",
                                            "iec 60364", "bs 7671", "iec 61850", "iec standard*", "sliis",
                                            "ceb standard*"]),
    "Quality / Lean": ("Professional", ["iso 9001", "six sigma", "lean manufacturing", "lean six sigma", "kaizen", "5s",
                                      "quality management"]),
    "Technical documentation": ("Professional", ["technical report*", "documentation", "as-built*", "datasheet*",
                                                 "technical drawings", "technical writing"]),
    "Chartered / IESL membership": ("Professional", ["chartered engineer*", "iesl", "ceng", "amie", "amiesl",
                                                     "ieee member*", "engineering council"]),
    "Customer & technical sales": ("Professional", ["technical sales", "pre-sales", "presales", "customer support",
                                                    "customer service", "account management"]),
    "Driving licence": ("Professional", ["driving licen*", "driving license*", "valid licen*", "light vehicle licen*"]),
}


@lru_cache(maxsize=1)
def categories() -> dict[str, str]:
    return {name: cat for name, (cat, _) in SKILLS.items()}


def category_of(skill: str) -> str:
    return categories().get(skill, "Other")


def extract_skills(text: str, extra: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Skills mentioned in `text`, in lexicon order. `extra` are skills of your own
    (config: coach.extra_skills), each matched under its own name."""
    if not text:
        return []
    found = [name for name, (_, aliases) in SKILLS.items()
             if any(keyword_pattern(a).search(text) for a in aliases)]
    found += [e for e in extra if e and e not in SKILLS and keyword_pattern(e).search(text)]
    return found
