"""Seed corpus: 36 complaints in the register real ones arrive in (§2.3).

Written as realistic Urdu-influenced English on purpose — it is what the keyword reader and
the LLM both have to cope with, and a dashboard demo against lorem ipsum proves nothing
about either. Spread across all six categories and all four statuses so pagination, filters
and the stats view all have something to show.

Each entry is (text, location, reporter_contact, status). Category and priority are NOT
listed: they are decided by the triage provider at seed time, which means the seed also
exercises the real triage path rather than hand-labelling around it.
"""

from app.domain.enums import Status

SEED_COMPLAINTS: list[tuple[str, str, str | None, Status]] = [
    # --- water -----------------------------------------------------------------
    (
        "Burst water main flooding Street 12 since fajr, water is entering ground floor "
        "of three houses. Please send team urgently, we have shifted children upstairs.",
        "Street 12, Gulberg III, Lahore",
        "0300-1234567",
        Status.IN_PROGRESS,
    ),
    (
        "No water supply in our lane for last three days. Tanker wala is charging 3000 "
        "rupees which we cannot afford daily. Boring is also not working.",
        "Lane 4, Sector G-9/2, Islamabad",
        "0321-9876543",
        Status.OPEN,
    ),
    (
        "Water pipeline is leaking just outside masjid gate, whole footpath is wet and "
        "slippery. Old people come for prayer and it is dangerous for them.",
        "Nazimabad No. 3, Karachi",
        None,
        Status.OPEN,
    ),
    (
        "Sewerage water is mixing with drinking water line near our street. Water is "
        "coming yellow and smelling badly, two children have loose motions since Tuesday.",
        "Mohalla Islampura, Faisalabad",
        "0333-4445556",
        Status.IN_PROGRESS,
    ),
    (
        "Main supply line valve is broken so water is going waste whole night in the "
        "drain. Kindly repair, it is wastage of clean water.",
        "Model Town Link Road, Lahore",
        None,
        Status.RESOLVED,
    ),
    (
        "Water pressure is very low on first floor since new construction started next "
        "door. Please check if they have connected illegally to our line.",
        "Block 6, PECHS, Karachi",
        "0345-1112223",
        Status.OPEN,
    ),
    # --- electricity -----------------------------------------------------------
    (
        "Live wire is hanging low over the street after last night storm, it is touching "
        "the wall when wind comes. Children play here in evening, please come today.",
        "Street 7, Shalimar Town, Lahore",
        "0301-2223334",
        Status.IN_PROGRESS,
    ),
    (
        "PMT transformer near our corner is sparking badly and making loud noise since "
        "morning. Last year same transformer caught fire so we are worried.",
        "Chungi Amar Sidhu, Lahore",
        "0302-5556667",
        Status.OPEN,
    ),
    (
        "Unannounced load shedding of six to seven hours daily in our area but bill is "
        "full. Please tell us the schedule at least so we can manage.",
        "Sector 11-B, North Karachi",
        None,
        Status.OPEN,
    ),
    (
        "Street pole wire got cut and is lying on the ground near the water tank. Bohat "
        "khatarnaak hai, someone can get shock while filling water.",
        "Dhoke Kala Khan, Rawalpindi",
        "0316-7778889",
        Status.IN_PROGRESS,
    ),
    (
        "Electricity meter reading is wrong, bill came 42000 for a two room house where "
        "only fan and bulb is used. Kindly send someone for checking.",
        "Mohalla Qadeer Abad, Multan",
        "0308-9990001",
        Status.REJECTED,
    ),
    (
        "Voltage is very low in evening time, fridge compressor is not starting and "
        "motor also does not run. Whole lane is facing same problem.",
        "Green Town Sector C-1, Lahore",
        None,
        Status.OPEN,
    ),
    # --- sanitation ------------------------------------------------------------
    (
        "Garbage has not been lifted from our corner point for ten days, kachra is now "
        "spread on the road and dogs are tearing the bags. Smell is unbearable.",
        "Street 22, Allama Iqbal Town, Lahore",
        "0311-4445556",
        Status.IN_PROGRESS,
    ),
    (
        "Gutter is overflowing on the main road and water is standing for one week now. "
        "Mosquitoes have increased and one dengue case is already reported in our street.",
        "Orangi Town Sector 5, Karachi",
        "0335-6667778",
        Status.OPEN,
    ),
    (
        "Manhole cover is missing since Eid holidays and hole is open in middle of the "
        "lane. At night nothing is visible, motorcycle already fell inside twice.",
        "Peoples Colony No. 1, Faisalabad",
        "0300-7778889",
        Status.IN_PROGRESS,
    ),
    (
        "Nala behind our houses is completely choked with plastic and mud. When it rains "
        "the dirty water comes inside our courtyard.",
        "Bhutta Chowk, Multan",
        None,
        Status.OPEN,
    ),
    (
        "People from other area are dumping construction waste on our empty plot at "
        "night. Whole plot has become a dump now, please stop them.",
        "Phase 4, DHA, Karachi",
        "0342-1112223",
        Status.REJECTED,
    ),
    (
        "Sewerage line is blocked and the water is coming back into bathroom drain of "
        "three houses. Plumber says it is main line problem, not ours.",
        "Mohalla Sethi Town, Peshawar",
        "0313-2223334",
        Status.OPEN,
    ),
    (
        "Public toilet at the bus stop is in very bad condition, no water and door is "
        "broken. Ladies cannot use it at all.",
        "General Bus Stand, Sargodha",
        None,
        Status.OPEN,
    ),
    # --- roads -----------------------------------------------------------------
    (
        "Very big khadda in the middle of the road near school gate, two motorcycles "
        "have fallen this week. One boy got injured on his knee badly.",
        "Near Govt Boys School, Ferozepur Road, Lahore",
        "0304-5556667",
        Status.IN_PROGRESS,
    ),
    (
        "Road was dug by gas company two months back and never repaired properly. Now "
        "the whole patch has sunk and rickshaws avoid our street.",
        "Street 9, Satellite Town, Rawalpindi",
        "0307-8889990",
        Status.OPEN,
    ),
    (
        "Traffic signal at the chowk is not working since last Friday, there is jam "
        "every morning and no warden is coming. Accident risk is high.",
        "Jail Road Chowk, Lahore",
        None,
        Status.IN_PROGRESS,
    ),
    (
        "Footpath is fully encroached by shopkeepers who have put their stalls on it, so "
        "students have to walk on the main road with traffic.",
        "Saddar Bazaar, Hyderabad",
        "0306-1112223",
        Status.OPEN,
    ),
    (
        "Speed breaker near the hospital gate is too high and unmarked, ambulance drivers "
        "complain and cars are getting damaged underneath.",
        "Outside DHQ Hospital, Gujranwala",
        None,
        Status.RESOLVED,
    ),
    (
        "Road carpeting work was left incomplete for last fifty meters of our street. "
        "Contractor took the machinery away three weeks ago.",
        "Street 15, Wapda Town, Lahore",
        "0322-4445556",
        Status.OPEN,
    ),
    (
        "Underpass is filling with rain water every time it rains because the pump is "
        "not working. Cars get stuck in the middle.",
        "Kalma Chowk Underpass, Lahore",
        None,
        Status.OPEN,
    ),
    # --- streetlights ----------------------------------------------------------
    (
        "All street lights of our lane are not working since one month, it is completely "
        "dark after maghrib. Ladies are afraid to come home from tuition.",
        "Street 5, Johar Town Block J, Lahore",
        "0309-7778889",
        Status.IN_PROGRESS,
    ),
    (
        "Two lamp posts are working but the remaining four bulbs are fused in our park. "
        "Please replace the bulbs, children play till late.",
        "Sector F-10 Park, Islamabad",
        None,
        Status.OPEN,
    ),
    (
        "Street light pole is bent and leaning towards the electricity wires after the "
        "truck hit it. It can fall on the wires any time.",
        "Korangi Industrial Area, Karachi",
        "0334-9990001",
        Status.OPEN,
    ),
    (
        "Street light stays on whole day and whole night in our street, it is wastage of "
        "electricity. Kindly fix the timer switch.",
        "Askari 10, Lahore Cantt",
        None,
        Status.RESOLVED,
    ),
    (
        "New street lights were installed but they are never switched on. Poles are "
        "standing since Ramzan without any light.",
        "Mohalla Rahim Yar, Bahawalpur",
        "0303-2223334",
        Status.OPEN,
    ),
    # --- other / mixed ---------------------------------------------------------
    (
        "Stray dogs have increased a lot near the children park, yesterday one dog bit a "
        "small boy on his leg. Please arrange the dog catching team.",
        "Iqbal Park, Sialkot",
        "0312-5556667",
        Status.IN_PROGRESS,
    ),
    (
        "A dead animal is lying in the empty plot beside our house for two days and the "
        "smell has spread to whole street. Nobody is picking it.",
        "Ravi Road, Lahore",
        None,
        Status.OPEN,
    ),
    (
        "Park boundary wall is broken from two sides and people enter at night to sit and "
        "make noise. Kindly repair the wall and lock the gate.",
        "Nishtar Park, Multan",
        "0315-8889990",
        Status.OPEN,
    ),
    (
        "Illegal marriage hall is running in our residential street, they park cars on "
        "both sides and play loud music till 2am. Nobody can sleep.",
        "Garden Town, Lahore",
        "0300-3334445",
        Status.REJECTED,
    ),
    (
        "Request for one more dustbin at the corner of our street, current one is always "
        "full by afternoon. Not urgent but would help keep the lane clean.",
        "Street 3, Chaklala Scheme 3, Rawalpindi",
        None,
        Status.OPEN,
    ),
]
