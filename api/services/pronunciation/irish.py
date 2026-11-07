"""How to say Irish first names, surnames and places.

English text-to-speech reads Irish spelling as English ("Sadhbh" comes out
as "Sarah", "Naas" as "Nars"), and so does a speech-to-speech model reading a
name from its instructions. Each entry here gives:

- the written forms it matches, with and without fadas;
- ``say``: an English respelling that English voices read the Irish way. It
  is what the speech engine is sent; transcripts, call logs and anything saved
  keep the real spelling;
- ``guide``: the same sound for a person or a language model, the stressed
  syllable in capitals;
- ``ipa``: an English-phoneme IPA approximation where the sound is settled;
- ``note``: common regional or family variants. The respelling gives the most
  widespread one.

Only names whose pronunciation is well established are listed; one that
varies a lot between families or regions is left out rather than guessed.

Three uses:

- :func:`respell` for any text about to be synthesised (pipeline voices and
  the demo recordings);
- :func:`respell_transform`, the same as a Pipecat ``text_transforms`` entry;
- :func:`realtime_guide`, a short pronunciation section for a
  speech-to-speech model's instructions, which has no synthesis step to
  rewrite.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

Kind = Literal["first_name", "surname", "place"]


@dataclass(frozen=True, slots=True)
class Pronunciation:
    spellings: tuple[str, ...]
    say: str
    guide: str
    kind: Kind
    ipa: str | None = None
    note: str = ""
    # Also match the spellings with fadas removed ("Siobhan" for "Siobhán").
    # Off where the bare form is another name or word ("Tomas", "Pol").
    match_without_fadas: bool = True

    @property
    def spelling(self) -> str:
        return self.spellings[0]

    def written_forms(self) -> tuple[str, ...]:
        forms: list[str] = []
        for spelling in self.spellings:
            for form in (spelling, strip_fadas(spelling)):
                wanted = form == spelling or self.match_without_fadas
                if wanted and form not in forms:
                    forms.append(form)
        return tuple(forms)


def strip_fadas(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize(
        "NFC", "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    )


def _f(*spellings: str, say: str, guide: str, ipa: str | None = None, **kw):
    return Pronunciation(spellings, say, guide, "first_name", ipa, **kw)


def _s(*spellings: str, say: str, guide: str, ipa: str | None = None, **kw):
    return Pronunciation(spellings, say, guide, "surname", ipa, **kw)


def _p(*spellings: str, say: str, guide: str, ipa: str | None = None, **kw):
    return Pronunciation(spellings, say, guide, "place", ipa, **kw)


# fmt: off
FIRST_NAMES: tuple[Pronunciation, ...] = (
    # Women
    _f("Aoife", say="Eefa", guide="EE-fa", ipa="ˈiːfə"),
    _f("Aoibhinn", "Aoibhín", say="Eeveen", guide="EE-veen", ipa="ˈiːviːn"),
    _f("Aoibheann", say="Eevin", guide="EE-vin", ipa="ˈiːvɪn"),
    _f("Aoibh", say="Eev", guide="EEV", ipa="ˈiːv"),
    _f("Caoimhe", say="Keeva", guide="KEE-va", ipa="ˈkiːvə"),
    _f("Sadhbh", "Sadbh", say="Sive", guide="SIVE (rhymes with five)", ipa="ˈsaɪv"),
    _f("Siobhán", say="Shiv-awn", guide="shiv-AWN", ipa="ʃɪˈvɔːn"),
    _f("Niamh", say="Neev", guide="NEEV", ipa="ˈniːv"),
    _f("Saoirse", say="Seer-sha", guide="SEER-sha", ipa="ˈsɪəɹʃə"),
    _f("Róisín", say="Ro-sheen", guide="ro-SHEEN", ipa="roʊˈʃiːn"),
    _f("Clodagh", say="Cloda", guide="CLO-da", ipa="ˈkloʊdə"),
    _f("Gráinne", say="Grawn-ya", guide="GRAW-nya", ipa="ˈɡɹɔːnjə"),
    _f("Ciara", say="Keera", guide="KEER-a", ipa="ˈkɪəɹə"),
    _f("Méabh", "Meadhbh", "Maeve", say="Mayv", guide="MAYV", ipa="ˈmeɪv"),
    _f("Orla", "Órla", "Orlaith", "Órlaith", say="Orla", guide="OR-la", ipa="ˈɔːɹlə"),
    _f("Sorcha", say="Sur-ka", guide="SUR-ka", note="also SOR-ka; in Irish SUR-a-kha"),
    _f("Éabha", say="Ayva", guide="AY-va", ipa="ˈeɪvə"),
    _f("Dearbhla", say="Dervla", guide="DER-vla", ipa="ˈdɛɹvlə"),
    _f("Aisling", "Aislinn", say="Ash-ling", guide="ASH-ling", ipa="ˈæʃlɪŋ"),
    _f("Bríd", say="Breed", guide="BREED", ipa="ˈbɹiːd"),
    _f("Nuala", say="Noola", guide="NOO-la", ipa="ˈnuːlə"),
    _f("Muireann", say="Mirren", guide="MIR-en", note="also MWIR-en"),
    _f("Ríona", say="Reeana", guide="REE-a-na"),
    _f("Fionnuala", "Fionnghuala", say="Fin-noola", guide="fin-NOO-la", ipa="fɪˈnuːlə"),
    _f("Eimear", "Éimear", "Eimhear", "Emer", say="Eemer", guide="EE-mer", ipa="ˈiːməɹ"),
    _f("Áine", say="Awn-ya", guide="AWN-ya", ipa="ˈɔːnjə"),
    _f("Sinéad", say="Shin-aid", guide="shin-AYD", ipa="ʃɪˈneɪd"),
    _f("Deirdre", say="Deer-dra", guide="DEER-dra", ipa="ˈdɪəɹdɹə"),
    _f("Síle", say="Sheela", guide="SHEE-la", ipa="ˈʃiːlə"),
    _f("Úna", say="Oona", guide="OO-na", ipa="ˈuːnə"),
    _f("Máire", say="Maw-ra", guide="MAW-ra", ipa="ˈmɔːɹə", note="also MOY-ra"),
    _f("Mairéad", say="Ma-raid", guide="ma-RAYD", ipa="məˈɹeɪd"),
    _f("Bláthnaid", say="Blaw-nid", guide="BLAW-nid", ipa="ˈblɔːnɪd"),
    _f("Laoise", say="Leesha", guide="LEE-sha", ipa="ˈliːʃə"),
    _f("Clíodhna", "Clíona", say="Klee-na", guide="KLEE-na", ipa="ˈkliːnə"),
    _f("Ailbhe", say="Alva", guide="AL-va", ipa="ˈælvə"),
    _f("Sláine", say="Slawn-ya", guide="SLAW-nya", ipa="ˈslɔːnjə"),
    _f("Treasa", say="Trassa", guide="TRA-sa", ipa="ˈtɹæsə"),
    _f("Nóirín", say="No-reen", guide="no-REEN", ipa="noʊˈɹiːn"),
    _f("Caitríona", say="Ka-treena", guide="ka-TREE-na", ipa="kəˈtɹiːnə"),
    _f("Neasa", say="Nassa", guide="NA-sa", ipa="ˈnæsə"),
    _f("Doireann", say="Dirren", guide="DIR-en"),
    _f("Eithne", say="Enya", guide="EN-ya", ipa="ˈɛnjə", note="also ETH-na"),
    _f("Fiadh", say="Fee-a", guide="FEE-a", ipa="ˈfiːə"),
    _f("Siún", say="Shoon", guide="SHOON", ipa="ˈʃuːn"),
    _f("Caoilfhionn", "Caoilinn", say="Keelin", guide="KEE-lin", ipa="ˈkiːlɪn"),
    _f("Éadaoin", say="Aydeen", guide="AY-deen", ipa="ˈeɪdiːn"),
    _f("Bébhinn", say="Bay-vin", guide="BAY-vin", ipa="ˈbeɪvɪn"),
    _f("Líadan", say="Leeadan", guide="LEE-a-dan", ipa="ˈliːədən"),
    _f("Íde", say="Eeda", guide="EE-da", ipa="ˈiːdə", match_without_fadas=False),
    _f("Mealla", say="Malla", guide="MAL-a", ipa="ˈmælə"),
    # Men
    _f("Tadhg", say="Tyg", guide="TIEG (like the start of tiger, then g)", ipa="ˈtaɪɡ"),
    _f("Cian", say="Kee-an", guide="KEE-an", ipa="ˈkiːən"),
    _f("Oisín", say="Ush-een", guide="ush-EEN", ipa="ʌˈʃiːn", note="also OSH-een"),
    _f("Domhnall", say="Doe-nal", guide="DOH-nal", ipa="ˈdoʊnəl"),
    _f("Dónal", "Donal", say="Doe-nal", guide="DOH-nal", ipa="ˈdoʊnəl"),
    _f("Eoghan", say="Owen", guide="OH-en", ipa="ˈoʊən"),
    _f("Eoin", say="Owen", guide="OH-in", ipa="ˈoʊɪn"),
    _f("Daithí", say="Dah-hee", guide="DAH-hee", ipa="ˈdɑːhiː"),
    _f("Cathal", say="Ka-hal", guide="KA-hal", ipa="ˈkæhəl"),
    _f("Rian", say="Ree-an", guide="REE-an", ipa="ˈɹiːən"),
    _f("Darragh", say="Darra", guide="DA-ra", ipa="ˈdæɹə"),
    _f("Cillian", say="Killian", guide="KILL-ee-an", ipa="ˈkɪliən"),
    _f("Ciarán", say="Keer-awn", guide="KEER-awn", ipa="ˈkɪəɹɔːn", note="also KEER-an"),
    _f("Pádraig", say="Paw-drig", guide="PAW-drig", ipa="ˈpɔːdɹɪɡ"),
    _f("Pádraic", say="Paw-drik", guide="PAW-drik", ipa="ˈpɔːdɹɪk"),
    _f("Seán", say="Shawn", guide="SHAWN", ipa="ˈʃɔːn"),
    _f("Séamus", say="Shay-mus", guide="SHAY-mus", ipa="ˈʃeɪməs"),
    _f("Fiachra", say="Fee-ak-ra", guide="FEE-akh-ra"),
    _f("Ruairí", "Ruaidhrí", say="Roo-ree", guide="ROO-ree", ipa="ˈɹuːɹi"),
    _f("Diarmuid", "Diarmaid", say="Deer-mid", guide="DEER-mid", ipa="ˈdɪəɹmɪd"),
    _f("Donnacha", "Donncha", "Donnchadh", say="Dunnaka", guide="DUN-a-kha"),
    _f("Colm", say="Kullum", guide="KUL-um", ipa="ˈkʌləm"),
    _f("Conall", say="Con-al", guide="KON-al", ipa="ˈkɒnəl", note="also KUN-al"),
    _f("Fergal", "Feargal", say="Fur-gal", guide="FUR-gal", ipa="ˈfɜːɹɡəl"),
    _f("Peadar", say="Padder", guide="PAD-er", ipa="ˈpædəɹ"),
    _f("Niall", say="Nye-al", guide="NYE-al", ipa="ˈnaɪəl", note="also NEE-al"),
    _f("Tomás", say="Toe-maws", guide="toe-MAWS", ipa="toʊˈmɔːs", note="also TOM-aws in Connacht and Ulster", match_without_fadas=False),
    _f("Mícheál", say="Mee-hawl", guide="MEE-hawl", ipa="ˈmiːhɔːl", match_without_fadas=False),
    _f("Odhrán", say="Oh-rawn", guide="OH-rawn", ipa="ˈoʊɹɔːn"),
    _f("Ruadhán", say="Roo-awn", guide="ROO-awn", ipa="ˈɹuːɔːn"),
    _f("Páidí", say="Paw-dee", guide="PAW-dee", ipa="ˈpɔːdi"),
    _f("Seosamh", say="Sho-sav", guide="SHOH-sav", ipa="ˈʃoʊsəv"),
    _f("Aodhán", say="Aydawn", guide="AY-dawn", ipa="ˈeɪdɔːn", note="also EE-dawn in Ulster"),
    _f("Caoimhín", say="Kwee-veen", guide="KWEE-veen", ipa="ˈkwiːviːn", note="also KEE-veen"),
    _f("Fionn", say="Finn", guide="FIN", ipa="ˈfɪn", note="also FYUN"),
    _f("Fionnán", say="Fin-awn", guide="FIN-awn", ipa="ˈfɪnɔːn"),
    _f("Tiarnán", say="Teer-nawn", guide="TEER-nawn", ipa="ˈtɪəɹnɔːn"),
    _f("Lochlann", "Lochlainn", say="Lock-lan", guide="LOKH-lan"),
    _f("Naoise", say="Neesha", guide="NEE-sha", ipa="ˈniːʃə"),
    _f("Cuán", say="Koo-awn", guide="KOO-awn", ipa="ˈkuːɔːn"),
    _f("Éanna", say="Ayna", guide="AY-na", ipa="ˈeɪnə"),
    _f("Iarla", say="Ear-la", guide="EER-la", ipa="ˈɪəɹlə"),
    _f("Bréanainn", say="Bray-nin", guide="BRAY-nin", ipa="ˈbɹeɪnɪn"),
    _f("Proinsias", say="Prun-shus", guide="PRUN-shus", ipa="ˈpɹʌnʃəs"),
    _f("Éamonn", "Éamon", say="Aymun", guide="AY-mun", ipa="ˈeɪmən"),
    _f("Féilim", "Feidhlim", say="Fay-lim", guide="FAY-lim", ipa="ˈfeɪlɪm"),
    _f("Colmán", say="Kul-mawn", guide="KUL-mawn", ipa="ˈkʌlmɔːn", match_without_fadas=False),
    _f("Ultán", say="Ul-tawn", guide="UL-tawn", ipa="ˈʌltɔːn"),
    _f("Pól", say="Pole", guide="POLE", ipa="ˈpoʊl", match_without_fadas=False),
    _f("Rónán", say="Ro-nawn", guide="ROH-nawn", ipa="ˈɹoʊnɔːn", match_without_fadas=False),
    _f("Turlough", say="Tur-lock", guide="TUR-lokh"),
    _f("Darach", say="Da-rak", guide="DA-rakh"),
    _f("Dáire", say="Daw-ra", guide="DAW-ra", ipa="ˈdɔːɹə"),
    _f("Aonghus", "Aengus", say="Ain-gus", guide="AIN-gus", ipa="ˈeɪŋɡəs"),
)

SURNAMES: tuple[Pronunciation, ...] = (
    # Irish-language forms. "Ó" is said "oh", "Ní" "nee", "Mac" "mok".
    _s("Ó Súilleabháin", say="Oh Soolavawn", guide="oh SOOL-a-vawn"),
    _s("Ó Briain", say="Oh Bree-an", guide="oh BREE-an"),
    _s("Ní Bhriain", say="Nee Vree-an", guide="nee VREE-an"),
    _s("Mac Giolla", say="Mock Gilla", guide="mok GIL-a"),
    _s("Ó Ceallaigh", say="Oh Kyal-ee", guide="oh KYAL-ee"),
    _s("Ó Néill", say="Oh Nail", guide="oh NAYL"),
    _s("Ó Dónaill", say="Oh Doe-nal", guide="oh DOH-nal"),
    _s("Ó Murchú", say="Oh Murra-hoo", guide="oh MUR-a-khoo"),
    _s("Ní Mhurchú", say="Nee Vurra-hoo", guide="nee VUR-a-khoo"),
    _s("Ó Sé", say="Oh Shay", guide="oh SHAY"),
    _s("Ó Dálaigh", say="Oh Daw-lee", guide="oh DAW-lee"),
    _s("Ó Ríordáin", say="Oh Reer-dawn", guide="oh REER-dawn"),
    _s("Ó Broin", say="Oh Brin", guide="oh BRIN"),
    _s("Ó Riain", say="Oh Ree-an", guide="oh REE-an"),
    _s("Mac Mathúna", say="Mock Ma-hoona", guide="mok MA-hoo-na"),
    _s("Ó Conaill", say="Oh Kun-al", guide="oh KUN-al"),
    _s("de Búrca", say="deh Boorka", guide="de BOOR-ka"),
    _s("Breathnach", say="Bran-ock", guide="BRAN-akh"),
    _s("Ó Cinnéide", say="Oh Kin-ayda", guide="oh kin-AY-da"),
    _s("Ó Tuama", say="Oh Tooma", guide="oh TOO-ma"),
    _s("Ó Loingsigh", say="Oh Ling-shee", guide="oh LING-shee"),
    # Anglicised forms English voices misread
    _s("Geoghegan", say="Gay-gan", guide="GAY-gan", ipa="ˈɡeɪɡən", note="also GAY-ha-gan in the midlands"),
    _s("Meagher", say="Mar", guide="MAR", ipa="ˈmɑːɹ", note="some families say MAH-her"),
    _s("Keogh", say="Kyoh", guide="KYOH", ipa="ˈkjoʊ", note="also KEE-oh"),
    _s("Kehoe", say="Kee-oh", guide="KEE-oh", ipa="ˈkiːoʊ"),
    _s("Behan", say="Bee-an", guide="BEE-an", ipa="ˈbiːən"),
    _s("Mulcahy", say="Mulkahee", guide="mul-KA-hee", ipa="mʌlˈkæhi"),
    _s("Haughey", say="Haw-hee", guide="HAW-hee", ipa="ˈhɔːhi"),
    _s("Ahern", "Aherne", say="Ah-hurn", guide="A-hern", ipa="ˈæhɜːɹn"),
    _s("Houlihan", say="Hool-i-han", guide="HOOL-i-han", ipa="ˈhuːlɪhən"),
    _s("Donoghue", "Donohoe", say="Dunna-hoo", guide="DUN-a-hoo", ipa="ˈdʌnəhuː"),
    _s("Tighe", say="Tie", guide="TIE", ipa="ˈtaɪ"),
    _s("Cahill", say="Ka-hill", guide="KA-hill", ipa="ˈkæhɪl"),
    _s("Mahony", "Mahoney", say="Ma-ha-nee", guide="MA-ha-nee", note="also MAH-nee"),
    _s("Moynihan", say="Moy-ni-han", guide="MOY-ni-han", ipa="ˈmɔɪnɪhən"),
    _s("Faherty", say="Fa-her-tee", guide="FA-her-tee", ipa="ˈfæhəɹti"),
    _s("Treacy", say="Tray-see", guide="TRAY-see", ipa="ˈtɹeɪsi"),
    _s("McGrath", "Magrath", say="Muh-Grah", guide="mc-GRAH", note="also mc-GRAW"),
    _s("Gallagher", say="Gallaher", guide="GAL-a-her", ipa="ˈɡæləhəɹ"),
    _s("Callaghan", say="Callahan", guide="KAL-a-han", ipa="ˈkæləhən"),
    _s("Monaghan", say="Monahan", guide="MON-a-han", ipa="ˈmɒnəhən"),
    _s("Kavanagh", "Cavanagh", say="Kavana", guide="KAV-a-na", ipa="ˈkævənə"),
    _s("McLoughlin", say="Mack-Locklin", guide="mc-LOCK-lin", ipa="məˈklɒklɪn"),
    _s("Loughnane", say="Lock-nane", guide="LOCK-nane", ipa="ˈlɒkneɪn"),
    _s("Gough", say="Goff", guide="GOFF", ipa="ˈɡɒf"),
    _s("Murtagh", say="Murta", guide="MUR-ta", ipa="ˈmɜːɹtə"),
    _s("Phelan", say="Fay-lan", guide="FAY-lan", ipa="ˈfeɪlən", note="also FEE-lan"),
    _s("Leahy", say="Lay-hee", guide="LAY-hee", ipa="ˈleɪhi"),
    _s("Fahy", say="Fa-hee", guide="FA-hee", ipa="ˈfæhi"),
    _s("Keaveney", say="Keev-nee", guide="KEEV-nee", ipa="ˈkiːvni"),
    _s("Clohessy", say="Klo-hessy", guide="KLO-hess-ee", ipa="ˈkloʊhɛsi"),
    _s("Kiely", say="Kye-lee", guide="KYE-lee", ipa="ˈkaɪli", note="also KEE-lee"),
)

PLACES: tuple[Pronunciation, ...] = (
    _p("Dún Laoghaire", say="Dun Leery", guide="dun LEER-ee", ipa="dʌn ˈlɪəɹi"),
    _p("Clonakilty", say="Clon-a-kilty", guide="clon-a-KIL-tee", ipa="ˌklɒnəˈkɪlti"),
    _p("Youghal", say="Yawl", guide="YAWL", ipa="ˈjɔːl"),
    _p("Drogheda", say="Draw-hed-a", guide="DRAW-hed-a", ipa="ˈdɹɔːhɛdə", note="also DROH-hed-a"),
    _p("Naas", say="Nace", guide="NACE (rhymes with face)", ipa="ˈneɪs"),
    _p("Cobh", say="Cove", guide="COVE", ipa="ˈkoʊv"),
    _p("Leixlip", say="Lex-lip", guide="LEX-lip", ipa="ˈlɛkslɪp"),
    _p("Portlaoise", say="Port-leesh", guide="port-LEESH", ipa="pɔːɹtˈliːʃ"),
    _p("Laois", say="Leesh", guide="LEESH", ipa="ˈliːʃ"),
    _p("Abbeyleix", say="Abbey-leeks", guide="abbey-LEEKS", ipa="ˌæbiˈliːks"),
    _p("Dundalk", say="Dun-dawk", guide="dun-DAWK", ipa="dʌnˈdɔːk"),
    _p("Athy", say="Uh-thigh", guide="a-THIGH", ipa="əˈθaɪ"),
    _p("Tuam", say="Choo-am", guide="CHOO-am", ipa="ˈtʃuːəm"),
    _p("Howth", say="Hoath", guide="HOATH (rhymes with both)", ipa="ˈhoʊθ"),
    _p("Ranelagh", say="Ranela", guide="RAN-a-la", ipa="ˈɹænələ"),
    _p("Raheny", say="Ra-heeny", guide="ra-HEE-nee", ipa="ɹəˈhiːni"),
    _p("Glendalough", say="Glenda-lock", guide="GLEN-da-lokh"),
    _p("Lough", say="Lock", guide="LOKH (as in loch)"),
    _p("Loughrea", say="Lock-ray", guide="lokh-RAY"),
    _p("Athenry", say="Ath-en-rye", guide="ath-en-RYE", ipa="ˌæθənˈɹaɪ"),
    _p("Thurles", say="Thur-less", guide="THUR-less", ipa="ˈθɜːɹlɪs"),
    _p("Leitrim", say="Lee-trim", guide="LEE-trim", ipa="ˈliːtɹɪm"),
    _p("Fermoy", say="Fer-moy", guide="fer-MOY", ipa="fəɹˈmɔɪ"),
    _p("Ballinasloe", say="Ballina-sloe", guide="bal-in-a-SLOE", ipa="ˌbælɪnəˈsloʊ"),
    _p("Lucan", say="Loo-can", guide="LOO-can", ipa="ˈluːkən"),
    _p("Cloughjordan", say="Clock-jordan", guide="clokh-JOR-dan"),
    _p("Ennistymon", say="Ennis-tie-mon", guide="ennis-TIE-mon", ipa="ˌɛnɪsˈtaɪmən"),
    _p("Carrick-on-Suir", say="Carrick-on-Shure", guide="carrick-on-SHURE", ipa="ˌkæɹɪk ɒn ˈʃʊəɹ"),
    _p("Gweedore", say="Gwee-door", guide="gwee-DOOR", ipa="ɡwiːˈdɔːɹ"),
    _p("Achill", say="Ack-ill", guide="ACK-ill", ipa="ˈækɪl"),
    _p("Templeogue", say="Temple-ogue", guide="temple-OHG", ipa="ˌtɛmpəlˈoʊɡ"),
    _p("Dalkey", say="Daw-kee", guide="DAW-kee", ipa="ˈdɔːki"),
    _p("Killiney", say="Kill-eye-nee", guide="kill-EYE-nee", ipa="kɪˈlaɪni"),
    _p("Phibsborough", "Phibsboro", say="Fibs-burra", guide="FIBS-bur-a", ipa="ˈfɪbzbəɹə"),
)
# fmt: on

LEXICON: tuple[Pronunciation, ...] = FIRST_NAMES + SURNAMES + PLACES

# The user's own list: the names said wrong most often, which a
# speech-to-speech model gets before the caller's name is known.
CORE_NAMES: tuple[str, ...] = (
    "Aoife",
    "Caoimhe",
    "Sadhbh",
    "Siobhán",
    "Niamh",
    "Saoirse",
    "Róisín",
    "Clodagh",
    "Gráinne",
    "Tadhg",
    "Cian",
    "Oisín",
    "Domhnall",
    "Eoghan",
    "Daithí",
    "Cathal",
    "Rian",
)


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, Pronunciation], re.Pattern[str]]:
    by_form: dict[str, Pronunciation] = {}
    for entry in LEXICON:
        for form in entry.written_forms():
            key = form.casefold()
            if key in by_form and by_form[key] is not entry:
                raise ValueError(f"{form!r} is listed twice")
            by_form[key] = entry
    # Longest first, so "Ó Néill" wins over a shorter overlapping form.
    forms = sorted(by_form, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![\w-])(?:"
        + "|".join(re.escape(f).replace("\\ ", " ").replace(" ", r"\s+") for f in forms)
        + r")(?![\w-])",
        re.IGNORECASE,
    )
    return by_form, pattern


def lookup(word: str) -> Pronunciation | None:
    """The entry for one written name or place, with or without fadas."""
    by_form, _ = _index()
    return by_form.get(re.sub(r"\s+", " ", word.strip()).casefold())


def find(text: str) -> list[Pronunciation]:
    """The entries named in ``text``, in the order they first appear."""
    by_form, pattern = _index()
    found: list[Pronunciation] = []
    for match in pattern.finditer(text or ""):
        entry = by_form[re.sub(r"\s+", " ", match.group(0)).casefold()]
        if entry not in found:
            found.append(entry)
    return found


def respell(text: str) -> str:
    """``text`` with every listed name replaced by its spoken respelling.

    For speech input only: never store or show the result.
    """
    if not text:
        return text
    by_form, pattern = _index()
    return pattern.sub(
        lambda m: by_form[re.sub(r"\s+", " ", m.group(0)).casefold()].say, text
    )


async def respell_transform(text: str, aggregation_type: object = None) -> str:
    """:func:`respell` as a Pipecat TTS ``text_transforms`` callable.

    Pipecat applies text transforms to the text it sends for synthesis only;
    the TTSTextFrame that feeds the transcript and the LLM context carries the
    text as the model wrote it.
    """
    return respell(text)


def guide_line(entry: Pronunciation) -> str:
    return f"{entry.spelling} = {entry.guide}"


def realtime_guide(
    texts: Iterable[str | None] = (),
    *,
    include_core: bool = True,
    limit: int = 40,
) -> str:
    """A short pronunciation section for a speech-to-speech model's instructions.

    Lists the core names (the ones callers' names most often are and voices
    most often get wrong) and every listed name or place found in ``texts``:
    the agent's own instructions, the business facts and what is known about
    the caller. Kept to one short paragraph so it costs little on every turn.
    """
    entries: list[Pronunciation] = []
    if include_core:
        entries.extend(e for e in map(lookup, CORE_NAMES) if e is not None)
    for text in texts:
        if not text:
            continue
        for entry in find(text):
            if entry not in entries:
                entries.append(entry)
    entries = entries[:limit]
    rule = (
        "# SAYING IRISH NAMES\n\n"
        "Say Irish names and places the Irish way, never as the English "
        "spelling suggests, and say a caller's name the way they said it. "
        "Write and save names with their normal spelling."
    )
    if not entries:
        return rule
    return f"{rule} Say: " + "; ".join(guide_line(e) for e in entries) + "."
