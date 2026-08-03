# openFDA Drug Data — Field Dictionary

Full per-field tables generated **directly from the `fields.yaml` specs** in `docs/Metadata/` (machine-generated, no manual editing).

Columns: **Field** (nesting shown with dots; `[]` = a list) · **Description** · **Type** · **Codes / values** (from `possible_values`; `—` = free text / no code list).

## Event — `drug/event (FAERS)`

Source: <https://open.fda.gov/apis/drug/event/searchable-fields/> · **89 fields**

| Field | Description | Type | Codes / values |
|---|---|---|---|
| `authoritynumb` | Populated with the Regulatory Authority’s case report number, when available. | string | — |
| `companynumb` | Identifier for the company providing the report. This is self-assigned. | string | — |
| `duplicate` | This value is `1` if earlier versions of this report were submitted to FDA. openFDA only shows the most recent version. | string | — |
| `fulfillexpeditecriteria` | Identifies expedited reports (those that were processed within 15 days). | string | 1=Yes; 2=No |
| `occurcountry` | The name of the country where the event occurred. | string | ref: Country codes |
| `patient.drug[].actiondrug` | Actions taken with the drug. | string | 1=Drug withdrawn; 2=Dose reduced; 3=Dose increased; 4=Dose not changed; 5=Unknown; 6=Not applicable |
| `patient.drug[].activesubstance.activesubstancename` | Product active ingredient, which may be different than other drug identifiers (when provided). | string | — |
| `patient.drug[].drugadditional` | Dechallenge outcome information—whether the event abated after product use stopped or the dose was reduced. Only present when this was attempted and the data was provided. | string | 1=Yes; 2=No; 3=Does not apply |
| `patient.drug[].drugadministrationroute` | The drug’s route of administration. | string | 001=Auricular (otic); 002=Buccal; 003=Cutaneous; 004=Dental; 005=Endocervical; 006=Endosinusial; 007=Endotracheal; 008=Epidural; 009=Extra-amniotic; 010=Hemodialysis; 011=Intra corpus cavernosum; 012=Intra-amniotic; 013=Intra-arterial; 014=Intra-articular; 015=Intra-uterine; 016=Intracardiac; 017=Intracavernous; 018=Intracerebral; 019=Intracervical; 020=Intracisternal; 021=Intracorneal; 022=Intracoronary; 023=Intradermal; 024=Intradiscal (intraspinal); 025=Intrahepatic; 026=Intralesional; 027=Intralymphatic; 028=Intramedullar (bone marrow); 029=Intrameningeal; 030=Intramuscular; 031=Intraocular; 032=Intrapericardial; 033=Intraperitoneal; 034=Intrapleural; 035=Intrasynovial; 036=Intratumor; 037=Intrathecal; 038=Intrathoracic; 039=Intratracheal; 040=Intravenous bolus; 041=Intravenous drip; 042=Intravenous (not otherwise specified); 043=Intravesical; 044=Iontophoresis; 045=Nasal; 046=Occlusive dressing technique; 047=Ophthalmic; 048=Oral; 049=Oropharingeal; 050=Other; 051=Parenteral; 052=Periarticular; 053=Perineural; 054=Rectal; 055=Respiratory (inhalation); 056=Retrobulbar; 057=Sunconjunctival; 058=Subcutaneous; 059=Subdermal; 060=Sublingual; 061=Topical; 062=Transdermal; 063=Transmammary; 064=Transplacental; 065=Unknown; 066=Urethral; 067=Vaginal |
| `patient.drug[].drugauthorizationnumb` | Drug authorization or application number (NDA or ANDA), if provided. | string | — |
| `patient.drug[].drugbatchnumb` | Drug product lot number, if provided. | string | — |
| `patient.drug[].drugcharacterization` | Reported role of the drug in the adverse event report. These values are not validated by FDA. | string | 1=Suspect (the drug was considered by the reporter to be the cause); 2=Concomitant (the drug was reported as being taken along with the suspect drug); 3=Interacting (the drug was considered by the reporter to have interacted with the suspect drug) |
| `patient.drug[].drugcumulativedosagenumb` | The cumulative dose taken until the first reaction was experienced, if provided. | string | — |
| `patient.drug[].drugcumulativedosageunit` | The unit for `drugcumulativedosagenumb`. | string | 001=kg (kilograms); 002=g (grams); 003=mg (milligrams); 004=µg (micrograms) |
| `patient.drug[].drugdosageform` | The drug’s dosage form. There is no standard, but values may include terms like `tablet` or `solution for injection`. | string | — |
| `patient.drug[].drugdosagetext` | Additional detail about the dosage taken. Frequently unknown, but occasionally including information like a brief textual description of the schedule of administration. | string | — |
| `patient.drug[].drugenddate` | Date the patient stopped taking the drug. | string | — |
| `patient.drug[].drugenddateformat` | Encoding format of the field `drugenddateformat`. Always set to `102` (YYYYMMDD). | string | — |
| `patient.drug[].drugindication` | Indication for the drug’s use. | string | — |
| `patient.drug[].drugintervaldosagedefinition` | The unit for the interval in the field `drugintervaldosageunitnumb.` | string | 801=Year; 802=Month; 803=Week; 804=Day; 805=Hour; 806=Minute; 807=Trimester; 810=Cyclical; 811=Trimester; 812=As necessary; 813=Total |
| `patient.drug[].drugintervaldosageunitnumb` | Number of units in the field `drugintervaldosagedefinition`. | string | — |
| `patient.drug[].drugrecurreadministration` | Whether the reaction occured after readministration of the drug. | string | 1=Yes; 2=No; 3=Unknown |
| `patient.drug[].drugrecurrence.drugrecuractionmeddraversion` | The version of MedDRA from which the term in `drugrecuraction` is drawn. | string | — |
| `patient.drug[].drugrecurrence.drugrecuraction` | Populated with the Reaction/Event information if/when `drugrecurreadministration` equals `1`. | string | — |
| `patient.drug[].drugseparatedosagenumb` | The number of separate doses that were administered. | string | — |
| `patient.drug[].drugstartdate` | Date the patient began taking the drug. | string | — |
| `patient.drug[].drugstartdateformat` | Encoding format of the field `drugstartdate`. Always set to `102` (YYYYMMDD). | string | — |
| `patient.drug[].drugstructuredosagenumb` | The number portion of a dosage; when combined with `drugstructuredosageunit` the complete dosage information is represented. For example, *300* in `300 mg`. | string | — |
| `patient.drug[].drugstructuredosageunit` | The unit for the field `drugstructuredosagenumb`. For example, *mg* in `300 mg`. | string | 001=kg (kilograms); 002=g (grams); 003=mg (milligrams); 004=µg (micrograms) |
| `patient.drug[].drugtreatmentduration` | The interval of the field `drugtreatmentdurationunit` for which the patient was taking the drug. | string | — |
| `patient.drug[].drugtreatmentdurationunit` | — | string | 801=Year; 802=Month; 803=Week; 804=Day; 805=Hour; 806=Minute |
| `patient.drug[].medicinalproduct` | Drug name. This may be the valid trade name of the product (such as `ADVIL` or `ALEVE`) or the generic name (such as `IBUPROFEN`). This field is not systematically normalized. It may contain misspellings or idiosyncrati… | string | — |
| `patient.drug[].openfda.application_number` | This corresponds to the NDA, ANDA, or BLA number reported by the labeler for products which have the corresponding Marketing Category designated. If the designated Marketing Category is OTC Monograph Final or OTC Monogr… | array of string | — |
| `patient.drug[].openfda.brand_name` | Brand or trade name of the drug product. | array of string | — |
| `patient.drug[].openfda.generic_name` | Generic name(s) of the drug product. | array of string | — |
| `patient.drug[].openfda.manufacturer_name` | Name of manufacturer or company that makes this drug product, corresponding to the labeler code segment of the NDC. | array of string | — |
| `patient.drug[].openfda.nui` | Unique identifier applied to a drug concept within the National Drug File Reference Terminology (NDF-RT). | array of string | ref: NDF-RT |
| `patient.drug[].openfda.package_ndc` | This number, known as the NDC, identifies the labeler, product, and trade package size. The first segment, the labeler code, is assigned by the FDA. A labeler is any firm that manufactures (including repackers or relabe… | array of string | — |
| `patient.drug[].openfda.pharm_class_cs` | Chemical structure classification of the drug product’s pharmacologic class. Takes the form of the classification, followed by `[Chemical/Ingredient]` (such as `Thiazides [Chemical/Ingredient]` or `Antibodies, Monoclona… | array of string | — |
| `patient.drug[].openfda.pharm_class_epc` | Established pharmacologic class associated with an approved indication of an active moiety (generic drug) that the FDA has determined to be scientifically valid and clinically meaningful. Takes the form of the pharmacol… | array of string | — |
| `patient.drug[].openfda.pharm_class_pe` | Physiologic effect or pharmacodynamic effect—tissue, organ, or organ system level functional activity—of the drug’s established pharmacologic class. Takes the form of the effect, followed by `[PE]` (such as `Increased D… | array of string | — |
| `patient.drug[].openfda.pharm_class_moa` | Mechanism of action of the drug—molecular, subcellular, or cellular functional activity—of the drug’s established pharmacologic class. Takes the form of the mechanism of action, followed by `[MoA]` (such as `Calcium Cha… | array of string | — |
| `patient.drug[].openfda.product_ndc` | The labeler manufacturer code and product code segments of the NDC number, separated by a hyphen. | array of string | — |
| `patient.drug[].openfda.product_type` | — | array of string | ref: Type of drug product |
| `patient.drug[].openfda.route` | The route of administation of the drug product. | array of string | ref: Route of administration |
| `patient.drug[].openfda.rxcui` | The RxNorm Concept Unique Identifier. RxCUI is a unique number that describes a semantic concept about the drug product, including its ingredients, strength, and dose forms. | array of string | ref: RxNorm and RxCUI documentation |
| `patient.drug[].openfda.spl_id` | Unique identifier for a particular version of a Structured Product Label for a product. Also referred to as the document ID. | array of string | — |
| `patient.drug[].openfda.spl_set_id` | Unique identifier for the Structured Product Label for a product, which is stable across versions of the label. Also referred to as the set ID. | array of string | — |
| `patient.drug[].openfda.substance_name` | The list of active ingredients of a drug product. | array of string | — |
| `patient.drug[].openfda.unii` | Unique Ingredient Identifier, which is a non-proprietary, free, unique, unambiguous, non-semantic, alphanumeric identifier based on a substance’s molecular structure and/or descriptive information. | array of string | ref: Unique Ingredient Identifiers |
| `patient.patientagegroup` | Populated with Patient Age Group code. | string | 1=Neonate; 2=Infant; 3=Child; 4=Adolescent; 5=Adult; 6=Elderly |
| `patient.patientdeath.patientdeathdate` | If the patient died, the date that the patient died. | string | — |
| `patient.patientdeath.patientdeathdateformat` | Encoding format of the field `patientdeathdate`. Always set to `102` (YYYYMMDD). | string | — |
| `patient.patientonsetage` | Age of the patient when the event first occured. | string | — |
| `patient.patientonsetageunit` | The unit for the interval in the field `patientonsetage.` | string | 800=Decade; 801=Year; 802=Month; 803=Week; 804=Day; 805=Hour |
| `patient.patientsex` | The sex of the patient. | string | 0=Unknown; 1=Male; 2=Female |
| `patient.patientweight` | The patient weight, in kg (kilograms). | string | — |
| `patient.reaction[].reactionmeddrapt` | Patient reaction, as a MedDRA term. Note that these terms are encoded in British English. For instance, diarrhea is spelled `diarrohea`. MedDRA is a standardized medical terminology. | string | ref: MedDRA |
| `patient.reaction[].reactionmeddraversionpt` | The version of MedDRA from which the term in `reactionmeddrapt` is drawn. | string | — |
| `patient.reaction[].reactionoutcome` | Outcome of the reaction in `reactionmeddrapt` at the time of last observation. | string | 1=Recovered/resolved; 2=Recovering/resolving; 3=Not recovered/not resolved; 4=Recovered/resolved with sequelae (consequent health issues); 5=Fatal; 6=Unknown |
| `patient.summary.narrativeincludeclinical` | Populated with Case Event Date, when available; does `NOT` include Case Narrative. | string | — |
| `primarysource.literaturereference` | Populated with the Literature Reference information, when available. | string | — |
| `primarysource.qualification` | Category of individual who submitted the report. | string | 1=Physician; 2=Pharmacist; 3=Other health professional; 4=Lawyer; 5=Consumer or non-health professional |
| `primarysource.reportercountry` | Country from which the report was submitted. | string | — |
| `primarysourcecountry` | Country of the reporter of the event. | string | ref: Country codes |
| `receiptdate` | Date that the _most recent_ information in the report was received by FDA. | string | — |
| `receiptdateformat` | Encoding format of the `receiptdate` field. Always set to 102 (YYYYMMDD). | string | — |
| `receivedate` | Date that the report was _first_ received by FDA. If this report has multiple versions, this will be the date the first version was received by FDA. | string | — |
| `receivedateformat` | Encoding format of the `receivedate` field. Always set to 102 (YYYYMMDD). | string | — |
| `receiver` | Information on the organization receiving the report. | object | — |
| `receiver.receiverorganization` | Name of the organization receiving the report. Because FDA received the report, the value is always `FDA`. | string | — |
| `receiver.receivertype` | The type of organization receiving the report. The value,`6`, is only specified if it is `other`, otherwise it is left blank. | string | 6=Other |
| `reportduplicate` | If a report is a duplicate or more recent version than a previously submitted report, this field will provide additional details on source provider. | object | — |
| `reportduplicate.duplicatenumb` | The case identifier for the duplicate. | string | — |
| `reportduplicate.duplicatesource` | The name of the organization providing the duplicate. | string | — |
| `reporttype` | Code indicating the circumstances under which the report was generated. | string | 1=Spontaneous; 2=Report from study; 3=Other; 4=Not available to sender (unknown) |
| `safetyreportid` | The 8-digit Safety Report ID number, also known as the case report number or case ID. The first 7 digits (before the hyphen) identify an individual report and the last digit (after the hyphen) is a checksum. This field… | string | — |
| `safetyreportversion` | The version number of the `safetyreportid`. Multiple versions of the same report may exist, it is generally best to only count the latest report and disregard others. openFDA will only return the latest version of a rep… | string | — |
| `sender.senderorganization` | Name of the organization sending the report. Because FDA is providing these reports to you, the value is always `FDA-Public Use.` | string | — |
| `sender.sendertype` | The name of the organization sending the report. Because FDA is providing these reports to you, the value is always `2`. | string | 2=Regulatory authority |
| `serious` | Seriousness of the adverse event. | string | 1=The adverse event resulted in death, a life threatening condition, hospitalization, disability, congenital anomaly, or other serious condition; 2=The adverse event did not result in any of the above |
| `seriousnesscongenitalanomali` | This value is `1` if the adverse event resulted in a congenital anomaly, and absent otherwise. | string | — |
| `seriousnessdeath` | This value is `1` if the adverse event resulted in death, and absent otherwise. | string | — |
| `seriousnessdisabling` | This value is `1` if the adverse event resulted in disability, and absent otherwise. | string | — |
| `seriousnesshospitalization` | This value is `1` if the adverse event resulted in a hospitalization, and absent otherwise. | string | — |
| `seriousnesslifethreatening` | This value is `1` if the adverse event resulted in a life threatening condition, and absent otherwise. | string | — |
| `seriousnessother` | This value is `1` if the adverse event resulted in some other serious condition, and absent otherwise. | string | — |
| `transmissiondate` | Date that the record was created. This may be earlier than the date the record was received by the FDA. | string | — |
| `transmissiondateformat` | Encoding format of the `transmissiondate` field. Always set to 102 (YYYYMMDD). | string | — |

## Label — `drug/label (SPL)`

Source: <https://open.fda.gov/apis/drug/label/searchable-fields/> · **118 fields**

> 86 `*_table` fields omitted — HTML-table copies of the free-text sections.

| Field | Description | Type | Codes / values |
|---|---|---|---|
| `abuse` | Information about the types of abuse that can occur with the drug and adverse reactions pertinent to those types of abuse, primarily based on human data. May include descriptions of particularly susceptible patient popu… | array of string | — |
| `accessories` | Documentation forthcoming. | array of string | — |
| `active_ingredient` | A list of the active, medicinal ingredients in the drug product. | array of string | — |
| `adverse_reactions` | Information about undesirable effects, reasonably associated with use of the drug, that may occur as part of the pharmacological action of the drug or may be unpredictable in its occurrence. Adverse reactions include th… | array of string | — |
| `alarms` | Documentation forthcoming. | array of string | — |
| `animal_pharmacology_and_or_toxicology` | Information from studies of the drug in animals, if the data were not relevant to nor included in other parts of the labeling. Most labels do not contain this field. | array of string | — |
| `ask_doctor` | Information about when a doctor should be consulted about existing conditions or sumptoms before using the drug product, including all warnings for persons with certain preexisting conditions (excluding pregnancy) and a… | array of string | — |
| `ask_doctor_or_pharmacist` | Information about when a doctor or pharmacist should be consulted about drug/drug or drug/food interactions before using a drug product. | array of string | — |
| `assembly_or_installation_instructions` | Documentation forthcoming. | array of string | — |
| `boxed_warning` | Information about contraindications or serious warnings, particularly those that may lead to death or serious injury. | array of string | — |
| `calibration_instructions` | Documentation forthcoming. | array of string | — |
| `carcinogenesis_and_mutagenesis_and_impairment_of_fertility` | Information about carcinogenic, mutagenic, or fertility impairment potential revealed by studies in animals. Information from human data about such potential is part of the `warnings` field. | array of string | — |
| `cleaning` | Documentation forthcoming. | array of string | — |
| `clinical_pharmacology` | Information about the clinical pharmacology and actions of the drug in humans. | array of string | — |
| `clinical_studies` | This field may contain references to clinical studies in place of detailed discussion in other sections of the labeling. | array of string | — |
| `compatible_accessories` | Documentation forthcoming. | array of string | — |
| `components` | Documentation forthcoming. | array of string | — |
| `contraindications` | Information about situations in which the drug product is contraindicated or should not be used because the risk of use clearly outweighs any possible benefit, including the type and nature of reactions that have been r… | array of string | — |
| `controlled_substance` | Information about the schedule in which the drug is controlled by the Drug Enforcement Administration, if applicable. | array of string | — |
| `dependence` | Information about characteristic effects resulting from both psychological and physical dependence that occur with the drug, the quantity of drug over a period of time that may lead to tolerance or dependence, details o… | array of string | — |
| `description` | General information about the drug product, including the proprietary and established name of the drug, the type of dosage form and route of administration to which the label applies, qualitative and quantitative ingred… | array of string | — |
| `diagram_of_device` | Documentation forthcoming. | array of string | — |
| `disposal_and_waste_handling` | — | array of string | — |
| `do_not_use` | Information about all contraindications for use. These contraindications are absolute and are intended for situations in which consumers should not use the product unless a prior diagnosis has been established by a doct… | array of string | — |
| `dosage_and_administration` | Information about the drug product’s dosage and administration recommendations, including starting dose, dose range, titration regimens, and any other clinically sigificant information that affects dosing recommendation… | array of string | — |
| `dosage_forms_and_strengths` | Information about all available dosage forms and strengths for the drug product to which the labeling applies. This field may contain descriptions of product appearance. | array of string | — |
| `drug_abuse_and_dependence` | Information about whether the drug is a controlled substance, the types of abuse that can occur with the drug, and adverse reactions pertinent to those types of abuse. | array of string | — |
| `drug_and_or_laboratory_test_interactions` | Information about any known interference by the drug with laboratory tests. | array of string | — |
| `drug_interactions` | Information about and practical guidance on preventing clinically significant drug/drug and drug/food interactions that may occur in people taking the drug. | array of string | — |
| `effective_time` | Date reference to the particular version of the labeling document. | string | — |
| `environmental_warning` | — | array of string | — |
| `food_safety_warning` | — | array of string | — |
| `general_precautions` | Information about any special care to be exercised for safe and effective use of the drug. | array of string | — |
| `geriatric_use` | Information about any limitations on any geriatric indications, needs for specific monitoring, hazards associated with use of the drug in the geriatric population. | array of string | — |
| `guaranteed_analysis_of_feed` | Documentation forthcoming. | array of string | — |
| `health_care_provider_letter` | Documentation forthcoming. | array of string | — |
| `health_claim` | Documentation forthcoming. | array of string | — |
| `how_supplied` | Information about the available dosage forms to which the labeling applies, and for which the manufacturer or distributor is responsible. This field ordinarily includes the strength of the dosage form (in metric units),… | array of string | — |
| `id` | The document ID, A globally unique identifier (GUID) for the particular revision of a labeling document. | string | — |
| `inactive_ingredient` | A list of inactive, non-medicinal ingredients in a drug product. | array of string | — |
| `indications_and_usage` | A statement of each of the drug product’s indications for use, such as for the treatment, prevention, mitigation, cure, or diagnosis of a disease or condition, or of a manifestation of a recognized disease or condition,… | array of string | — |
| `information_for_owners_or_caregivers` | Documentation forthcoming. | array of string | — |
| `information_for_patients` | Information necessary for patients to use the drug safely and effectively, such as precautions concerning driving or the concomitant use of other substances that may have harmful additive effects. | array of string | — |
| `instructions_for_use` | Information about safe handling and use of the drug product. | array of string | — |
| `intended_use_of_the_device` | Documentation forthcoming. | array of string | — |
| `keep_out_of_reach_of_children` | Information pertaining to whether the product should be kept out of the reach of children, and instructions about what to do in the case of accidental contact or ingestion, if appropriate. | array of string | — |
| `labor_and_delivery` | Information about the drug’s use during labor or delivery, whether or not the use is stated in the indications section of the labeling, including the effect of the drug on the mother and fetus, on the duration of labor… | array of string | — |
| `laboratory_tests` | Information on laboratory tests helpful in following the patient’s response to the drug or in identifying possible adverse reactions. If appropriate, information may be provided on such factors as the range of normal an… | array of string | — |
| `mechanism_of_action` | Information about the established mechanism(s) of the drug’s action in humans at various levels (for example receptor, membrane, tissue, organ, whole body). If the mechanism of action is not known, this field contains a… | array of string | — |
| `microbiology` | Documentation forthcoming. | array of string | — |
| `nonclinical_toxicology` | Information about toxicology in non-human subjects. | array of string | — |
| `nonteratogenic_effects` | Other information about the drug’s effects on reproduction and the drug’s use during pregnancy, if the information is relevant to the safe and effective use of the drug. | array of string | — |
| `nursing_mothers` | Information about excretion of the drug in human milk and effects on the nursing infant, including pertinent adverse effects observed in animal offspring. | array of string | — |
| `openfda.application_number` | This corresponds to the NDA, ANDA, or BLA number reported by the labeler for products which have the corresponding Marketing Category designated. If the designated Marketing Category is OTC Monograph Final or OTC Monogr… | array of string | — |
| `openfda.brand_name` | Brand or trade name of the drug product. | array of string | — |
| `openfda.generic_name` | Generic name(s) of the drug product. | array of string | — |
| `openfda.is_original_packager` | Whether or not the drug has been repackaged for distribution. | string | — |
| `openfda.manufacturer_name` | Name of manufacturer or company that makes this drug product, corresponding to the labeler code segment of the NDC. | array of string | — |
| `openfda.nui` | Unique identifier applied to a drug concept within the National Drug File Reference Terminology (NDF-RT). | array of string | ref: NDF-RT |
| `openfda.original_packager_product_ndc` | This ndc identifies the original packager. | array of string | — |
| `openfda.package_ndc` | This number, known as the NDC, identifies the labeler, product, and trade package size. The first segment, the labeler code, is assigned by the FDA. A labeler is any firm that manufactures (including repackers or relabe… | array of string | — |
| `openfda.pharm_class_cs` | Chemical structure classification of the drug product’s pharmacologic class. Takes the form of the classification, followed by `[Chemical/Ingredient]` (such as `Thiazides [Chemical/Ingredient]` or `Antibodies, Monoclona… | array of string | — |
| `openfda.pharm_class_epc` | Established pharmacologic class associated with an approved indication of an active moiety (generic drug) that the FDA has determined to be scientifically valid and clinically meaningful. Takes the form of the pharmacol… | array of string | — |
| `openfda.pharm_class_pe` | Physiologic effect or pharmacodynamic effect—tissue, organ, or organ system level functional activity—of the drug’s established pharmacologic class. Takes the form of the effect, followed by `[PE]` (such as `Increased D… | array of string | — |
| `openfda.pharm_class_moa` | Mechanism of action of the drug—molecular, subcellular, or cellular functional activity—of the drug’s established pharmacologic class. Takes the form of the mechanism of action, followed by `[MoA]` (such as `Calcium Cha… | array of string | — |
| `openfda.product_ndc` | The labeler manufacturer code and product code segments of the NDC number, separated by a hyphen. | array of string | — |
| `openfda.product_type` | — | array of string | ref: Type of drug product |
| `openfda.route` | The route of administation of the drug product. | array of string | ref: Route of administration |
| `openfda.rxcui` | The RxNorm Concept Unique Identifier. RxCUI is a unique number that describes a semantic concept about the drug product, including its ingredients, strength, and dose forms. | array of string | ref: RxNorm and RxCUI documentation |
| `openfda.spl_id` | Unique identifier for a particular version of a Structured Product Label for a product. Also referred to as the document ID. | array of string | — |
| `openfda.spl_set_id` | Unique identifier for the Structured Product Label for a product, which is stable across versions of the label. Also referred to as the set ID. | array of string | — |
| `openfda.substance_name` | The list of active ingredients of a drug product. | array of string | — |
| `openfda.unii` | Unique Ingredient Identifier, which is a non-proprietary, free, unique, unambiguous, non-semantic, alphanumeric identifier based on a substance’s molecular structure and/or descriptive information. | array of string | ref: Unique Ingredient Identifiers |
| `openfda.upc` | Universal Product Code | array of string | ref: Universal Product Code |
| `other_safety_information` | Information about safe use and handling of the product that may not have been specified in another field. | array of string | — |
| `overdosage` | Information about signs, symptoms, and laboratory findings of acute ovedosage and the general principles of overdose treatment. | array of string | — |
| `package_label_principal_display_panel` | The content of the principal display panel of the product package, usually including the product’s name, dosage forms, and other key information about the drug product. | array of string | — |
| `patient_medication_information` | Information or instructions to patients about safe use of the drug product, sometimes including a reference to a patient medication guide or counseling materials. | array of string | — |
| `pediatric_use` | Information about any limitations on any pediatric indications, needs for specific monitoring, hazards associated with use of the drug in any subsets of the pediatric population (such as neonates, infants, children, or… | array of string | — |
| `pharmacodynamics` | Information about any biochemical or physiologic pharmacologic effects of the drug or active metabolites related to the drug’s clinical effect in preventing, diagnosing, mitigating, curing, or treating disease, or those… | array of string | — |
| `pharmacogenomics` | Documentation forthcoming. | array of string | — |
| `pharmacokinetics` | Information about the clinically significant pharmacokinetics of a drug or active metabolites, for instance pertinent absorption, distribution, metabolism, and excretion parameters. | array of string | — |
| `precautions` | Information about any special care to be exercised for safe and effective use of the drug. | array of string | — |
| `pregnancy` | Information about effects the drug may have on pregnant women or on a fetus. This field may be ommitted if the drug is not absorbed systemically and the drug is not known to have a potential for indirect harm to the fet… | array of string | — |
| `pregnancy_or_breast_feeding` | Documentation forthcoming. | array of string | — |
| `purpose` | Information about the drug product’s indications for use. | array of string | — |
| `questions` | A telephone number of a source to answer questions about a drug product. Sometimes available days and times are also noted. | array of string | — |
| `recent_major_changes` | A list of the section(s) that contain substantive changes that have been approved by FDA in the product labeling. The headings and subheadings, if appropriate, affected by the change are listed together with each sectio… | array of string | — |
| `references` | This field may contain references when prescription drug labeling must summarize or otherwise relay on a recommendation by an authoritative scientific body, or on a standardized methodology, scale, or technique, because… | array of string | — |
| `residue_warning` | Documentation forthcoming. | array of string | — |
| `risks` | Documentation forthcoming. | array of string | — |
| `route` | Documentation forthcoming. | array of string | — |
| `safe_handling_warning` | Documentation forthcoming. | array of string | — |
| `set_id` | The Set ID, A globally unique identifier (GUID) for the labeling, stable across all versions or revisions. | string | — |
| `spl_indexing_data_elements` | Documentation forthcoming. | array of string | — |
| `spl_medguide` | Information about the patient medication guide that accompanies the drug product. Certain drugs must be dispensed with an accompanying medication guide. This field may contain information about when to consult the medic… | array of string | — |
| `spl_patient_package_insert` | Information necessary for patients to use the drug safely and effectively. | array of string | — |
| `spl_product_data_elements` | Usually a list of ingredients in a drug product. | array of string | — |
| `spl_unclassified_section` | Information not classified as belonging to one of the other fields. Approximately 40% of labeling with `effective_time` between June 2009 and August 2014 have information in this field. | array of string | — |
| `statement_of_identity` | Documentation forthcoming. | array of string | — |
| `stop_use` | Information about when use of the drug product should be discontinued immediately and a doctor consulted. Includes information about any signs of toxicity or other reactions that would necessitate immediately discontinu… | array of string | — |
| `storage_and_handling` | Information about safe storage and handling of the drug product. | array of string | — |
| `summary_of_safety_and_effectiveness` | Documentation forthcoming. | array of string | — |
| `teratogenic_effects` | _Pregnancy category A_: Adequate and well-controlled studies in pregnant women have failed to demonstrate a risk to the fetus in the first trimester of pregnancy, and there is no evidence of a risk in later trimesters.… | array of string | — |
| `troubleshooting` | Documentation forthcoming. | array of string | — |
| `use_in_specific_populations` | Information about use of the drug by patients in specific populations, including pregnant women and nursing mothers, pediatric patients, and geriatric patients. | array of string | — |
| `user_safety_warnings` | When a drug can pose a hazard to human health by contact, inhalation, ingestion, injection, or by any exposure, this field contains information which can prevent or decrease the possibility of harm. | array of string | — |
| `version` | A sequentially increasing number identifying the particular version of a document, starting with `1`. | string | — |
| `warnings` | Information about serious adverse reactions and potential safety hazards, including limitations in use imposed by those hazards and steps that should be taken if they occur. | array of string | — |
| `warnings_and_cautions` | Documentation forthcoming. | array of string | — |
| `when_using` | Information about side effects that people may experience, and the substances (e.g. alcohol) or activities (e.g. operating machinery, driving a car) to avoid while using the drug product. | array of string | — |
| `meta` | This section contains a disclaimer and license information. The field `last_updated` indicates when the data files were exported. | object | — |
| `meta.disclaimer` | Important details notes about openFDA data and limitations of the dataset. | string | — |
| `meta.license` | Link to a web page with license terms that govern data within openFDA. | string | — |
| `meta.last_updated` | The last date when this openFDA endpoint was updated. Note that this does not correspond to the most recent record for the endpoint or dataset. Rather, it is the last time the openFDA API was itself updated. | string | — |
| `meta.results.skip` | Offset (page) of results, defined by the `skip` [query parameter](/api/). | number | — |
| `meta.results.limit` | Number of records in this return, defined by the `limit` [query parameter](/api/). If there is no `limit` parameter, the API returns one result. | number | — |
| `meta.results.total` | Total number of records matching the search criteria. | number | — |

## NDC — `drug/ndc (National Drug Code)`

Source: <https://open.fda.gov/apis/drug/ndc/searchable-fields/> · **36 fields**

| Field | Description | Type | Codes / values |
|---|---|---|---|
| `product_id` | ProductID is a concatenation of the NDC product code and SPL documentID. | string | — |
| `product_ndc` | The labeler manufacturer code and product code segments of the NDC number, separated by a hyphen. | string | — |
| `spl_id` | Unique identifier for a particular version of a Structured Product Label for a product. Also referred to as the document ID. | string | — |
| `product_type` | Type of drug product | string | — |
| `finished` | Details whether the product is finished or not. FDA does not review and approve unfinished products. Therefore, all products in this file are considered unapproved. | string | — |
| `brand_name` | Brand or trade name of the drug product. | string | — |
| `brand_name_base` | The base of the brand name excluding its suffix. | string | — |
| `brand_name_suffix` | A suffix to the proprietary name, a value here should be appended to the ProprietaryName field to obtain the complete name of the product. This suffix is often used to distinguish characteristics of a product such as ex… | string | — |
| `generic_name` | Generic name(s) of the drug product. | string | — |
| `dosage_form` | The drug’s dosage form. There is no standard, but values may include terms like `tablet` or `solution for injection`. | string | — |
| `route` | The route of administation of the drug product. | string | — |
| `marketing_start_date` | This is the date that the labeler indicates was the start of its marketing of the drug product. | type | — |
| `marketing_end_date` | This is the date the product will no longer be available on the market. | string | — |
| `marketing_category` | Product types are broken down into several potential Marketing Categories, such as NDA/ANDA/BLA, OTC Monograph, or Unapproved Drug. | string | — |
| `application_number` | This corresponds to the NDA, ANDA, or BLA number reported by the labeler for products which have the corresponding Marketing Category designated. If the designated Marketing Category is OTC Monograph Final or OTC Monogr… | string | — |
| `pharm_class` | These are the reported pharmacological class categories corresponding to the SubstanceNames listed above. | string | — |
| `dea_schedule` | This is the assigned DEA Schedule number as reported by the labeler. Values are CI, CII, CIII, CIV, and CV. | string | 1=CI; 2=CII; 3=CIII; 4=CIV; 5=CV |
| `listing_expiration_date` | This is the date when the listing record will expire if not updated or certified by the firm. | string | — |
| `active_ingredients.name` | The names of the active, medicinal ingredients in the drug product. | string | — |
| `active_ingredients.strength` | The strength of the active, medicinal ingredients in the drug product. | string | — |
| `packaging.package_ndc` | This number, known as the NDC, identifies the labeler, product, and trade package size. The first segment, the labeler code, is assigned by the FDA. A labeler is any firm that manufactures (including repackers or relabe… | string | — |
| `packaging.description` | A description of the size and type of packaging in sentence form. Multilevel packages will have the descriptions concatenated together. | string | — |
| `packaging.marketing_start_date` | This is the date that the labeler indicates was the start of its marketing of the drug product. | string | — |
| `packaging.marketing_end_date` | This is the date the product will no longer be available on the market. | string | — |
| `packaging.sample` | Indicates whether this is a sample packaging or not. | string | — |
| `openfda.is_original_packager` | Whether or not the drug has been repackaged for distribution. | string | — |
| `openfda.manufacturer_name` | Name of manufacturer or company that makes this drug product, corresponding to the labeler code segment of the NDC. | string | — |
| `openfda.nui` | Unique identifier applied to a drug concept within the National Drug File Reference Terminology (NDF-RT). | string | — |
| `openfda.pharm_class_cs` | Chemical structure classification of the drug product’s pharmacologic class. Takes the form of the classification, followed by `[Chemical/Ingredient]` (such as `Thiazides [Chemical/Ingredient]` or `Antibodies, Monoclona… | string | — |
| `openfda.pharm_class_epc` | Established pharmacologic class associated with an approved indication of an active moiety (generic drug) that the FDA has determined to be scientifically valid and clinically meaningful. Takes the form of the pharmacol… | string | — |
| `openfda.pharm_class_moa` | Mechanism of action of the drug—molecular, subcellular, or cellular functional activity—of the drug’s established pharmacologic class. Takes the form of the mechanism of action, followed by `[MoA]` (such as `Calcium Cha… | string | — |
| `openfda.pharm_class_pe` | Physiologic effect or pharmacodynamic effect—tissue, organ, or organ system level functional activity—of the drug’s established pharmacologic class. Takes the form of the effect, followed by `[PE]` (such as `Increased D… | string | — |
| `openfda.rxcui` | The RxNorm Concept Unique Identifier. RxCUI is a unique number that describes a semantic concept about the drug product, including its ingredients, strength, and dose forms. | string | — |
| `openfda.spl_set_id` | Unique identifier for the Structured Product Label for a product, which is stable across versions of the label. Also referred to as the set ID. | string | — |
| `openfda.unii` | Unique Ingredient Identifier, which is a non-proprietary, free, unique, unambiguous, non-semantic, alphanumeric identifier based on a substance’s molecular structure and/or descriptive information. | string | — |
| `openfda.upc` | Universal Product Code | string | — |
