# ruff: noqa
"""Seed list for the teaching asset library: (slug, title, subject, classes, query, key_terms, model3d)."""

T = lambda slug, title, subject, classes, query, terms, model=None, aliases=(): dict(  # noqa: E731
    slug=slug, title=title, subject=subject, classes=classes, query=query, key_terms=terms, model3d=model, aliases=list(aliases)
)

TOPICS = [
    # --- lesson topics in the student test data first ---
    T("day-and-night", "Why do we have day and night?", "Science", [3, 4, 5, 6], "day and night earth rotation diagram", ["Axis", "Day side", "Night side", "Rotation"], "earth-axis", ["day night", "earth rotation", "rotation of earth"]),
    T("linear-equations", "Linear Equations", "Mathematics", [7, 8, 9, 10], "linear equation graph y=mx+c", ["Slope", "Intercept", "Variable", "Solution"], None, ["linear equation", "straight line graph"]),
    T("adding-fractions", "Adding fractions", "Mathematics", [3, 4, 5, 6], "fraction circles pie addition", ["Numerator", "Denominator", "Common denominator"], None, ["fractions", "fraction"]),
    # --- science ---
    T("seasons", "Seasons of the year", "Science", [4, 5, 6, 7], "seasons earth orbit tilt diagram", ["Tilt", "Orbit", "Summer", "Winter"], "earth-axis", ["season", "why seasons"]),
    T("solar-system", "The Solar System", "Science", [3, 4, 5, 6, 7], "solar system planets diagram", ["Sun", "Planets", "Orbit"], "solar-system", ["planets", "sun and planets"]),
    T("phases-of-moon", "Phases of the Moon", "Science", [5, 6, 7], "phases of the moon diagram", ["New moon", "Full moon", "Crescent"], "moon", ["moon phases", "moon"]),
    T("photosynthesis", "Photosynthesis", "Science", [5, 6, 7, 8, 9, 10], "photosynthesis diagram leaf sunlight carbon dioxide", ["Sunlight", "Chlorophyll", "Glucose", "Oxygen"], None, ["how plants make food"]),
    T("water-cycle", "The Water Cycle", "Science", [3, 4, 5, 6, 7], "water cycle diagram evaporation condensation precipitation", ["Evaporation", "Condensation", "Precipitation"], None, ["rain cycle"]),
    T("parts-of-a-plant", "Parts of a Plant", "Science", [1, 2, 3, 4], "parts of a plant root stem leaf flower diagram", ["Root", "Stem", "Leaf", "Flower"], None, ["plant parts"]),
    T("parts-of-a-flower", "Parts of a Flower", "Science", [5, 6, 7], "flower anatomy diagram stamen pistil petal", ["Petal", "Stamen", "Pistil", "Sepal"], None, ["flower"]),
    T("food-chain", "Food Chains", "Science", [4, 5, 6, 7], "food chain diagram producer consumer", ["Producer", "Consumer", "Decomposer"], None, ["food web"]),
    T("states-of-matter", "States of Matter", "Science", [3, 4, 5, 6, 7, 8], "states of matter solid liquid gas diagram", ["Solid", "Liquid", "Gas"], None, ["solid liquid gas"]),
    T("digestive-system", "The Human Digestive System", "Science", [5, 6, 7, 8], "human digestive system diagram", ["Stomach", "Intestine", "Oesophagus"], None, ["digestion"]),
    T("human-heart", "The Human Heart and Circulation", "Science", [6, 7, 8, 9, 10], "human heart diagram labelled", ["Atrium", "Ventricle", "Aorta"], None, ["heart", "circulatory system"]),
    T("respiratory-system", "The Respiratory System", "Science", [6, 7, 8, 9], "human respiratory system diagram lungs", ["Lungs", "Trachea", "Diaphragm"], None, ["lungs", "breathing"]),
    T("human-skeleton", "The Human Skeleton", "Science", [4, 5, 6, 7], "human skeleton diagram bones", ["Skull", "Ribs", "Spine"], None, ["bones", "skeleton"]),
    T("animal-cell", "Cell Structure", "Science", [7, 8, 9, 10], "animal cell diagram labelled organelles", ["Nucleus", "Cytoplasm", "Membrane", "Mitochondria"], None, ["cell", "plant and animal cell"]),
    T("electric-circuit", "Simple Electric Circuit", "Science", [5, 6, 7, 8], "simple electric circuit diagram battery bulb switch", ["Battery", "Bulb", "Switch", "Wire"], None, ["circuit", "electricity"]),
    T("magnets", "Magnets", "Science", [3, 4, 5, 6], "bar magnet field lines iron filings", ["North pole", "South pole", "Field lines"], None, ["magnet", "magnetism"]),
    T("reflection-of-light", "Reflection of Light", "Science", [6, 7, 8, 9, 10], "reflection of light plane mirror diagram angle of incidence", ["Incident ray", "Reflected ray", "Normal"], None, ["light", "mirror"]),
    T("atom-structure", "Structure of an Atom", "Science", [8, 9, 10], "atom structure diagram proton neutron electron", ["Proton", "Neutron", "Electron", "Nucleus"], "atom", ["atom", "atomic structure"]),
    T("rock-cycle", "Rocks and the Rock Cycle", "Science", [6, 7, 8], "rock cycle diagram igneous sedimentary metamorphic", ["Igneous", "Sedimentary", "Metamorphic"], None, ["rocks"]),
    T("layers-of-earth", "Layers of the Earth", "Geography", [6, 7, 8], "layers of the earth crust mantle core diagram", ["Crust", "Mantle", "Core"], "earth-layers", ["earth structure", "interior of earth"]),
    # --- mathematics ---
    T("types-of-triangles", "Types of Triangles", "Mathematics", [4, 5, 6, 7], "types of triangles equilateral isosceles scalene diagram", ["Equilateral", "Isosceles", "Scalene"], "pyramid", ["triangle", "triangles"]),
    T("angles", "Angles", "Mathematics", [4, 5, 6, 7], "types of angles acute right obtuse diagram", ["Acute", "Right", "Obtuse", "Reflex"], None, ["angle"]),
    T("parts-of-a-circle", "Parts of a Circle", "Mathematics", [5, 6, 7, 8, 9], "circle radius diameter chord circumference diagram", ["Radius", "Diameter", "Chord", "Circumference"], None, ["circle"]),
    T("area-and-perimeter", "Area and Perimeter", "Mathematics", [4, 5, 6, 7], "area and perimeter rectangle square diagram", ["Area", "Perimeter", "Length", "Breadth"], None, ["perimeter", "area"]),
    T("number-line", "The Number Line", "Mathematics", [1, 2, 3, 4], "number line integers diagram", ["Zero", "Positive", "Negative"], None, ["number lines", "integers"]),
    T("pythagoras-theorem", "Pythagoras Theorem", "Mathematics", [8, 9, 10], "pythagorean theorem right triangle squares diagram", ["Hypotenuse", "Base", "Perpendicular"], None, ["pythagoras", "right angled triangle"]),
    T("symmetry", "Symmetry", "Mathematics", [3, 4, 5, 6, 7], "line of symmetry butterfly diagram", ["Line of symmetry", "Mirror image"], None, ["lines of symmetry"]),
    T("solid-shapes", "3D Shapes", "Mathematics", [2, 3, 4, 5, 6, 7, 8], "3D solid shapes cube cuboid cylinder cone sphere", ["Cube", "Cylinder", "Cone", "Sphere"], "cube", ["cube", "cuboid", "cylinder", "cone", "sphere", "solid shapes"]),
    T("bar-graph", "Bar Graphs and Data Handling", "Mathematics", [3, 4, 5, 6, 7], "bar graph example chart", ["Axis", "Scale", "Bar"], None, ["data handling", "bar chart"]),
    # --- geography / social ---
    T("continents-and-oceans", "Continents and Oceans", "Geography", [3, 4, 5, 6], "world map continents oceans", ["Asia", "Africa", "Pacific Ocean"], "earth-axis", ["continents", "oceans", "world map"]),
    T("india-physical-map", "India: Physical Features", "Geography", [5, 6, 7, 8, 9], "India physical map himalayas ganga plains", ["Himalayas", "Ganga plain", "Deccan plateau"], None, ["india map", "physical map of india"]),
    T("latitude-longitude", "Latitudes and Longitudes", "Geography", [6, 7, 8, 9], "latitude longitude globe equator prime meridian diagram", ["Equator", "Prime meridian", "Tropic of Cancer"], "earth-axis", ["latitude", "longitude", "equator"]),
    T("volcano", "Volcanoes", "Geography", [6, 7, 8], "volcano cross section diagram magma vent crater", ["Magma", "Vent", "Crater"], None, ["volcanoes"]),
    T("indus-valley", "Indus Valley Civilisation", "History", [6, 7, 8], "Indus Valley Civilisation Mohenjo-daro great bath", ["Harappa", "Mohenjo-daro", "Great Bath"], None, ["harappan civilisation"]),
    T("taj-mahal", "The Mughal Empire and the Taj Mahal", "History", [6, 7, 8], "Taj Mahal Agra", ["Shah Jahan", "Marble", "Agra"], None, ["mughals", "mughal empire"]),
]
