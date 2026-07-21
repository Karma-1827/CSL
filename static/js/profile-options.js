(() => {
  "use strict";

  const LANGUAGE_CODES = "zh en ja ko vi id th tl ms hi fr de es it pt ru ar af am as az be bg bn bo bs ca cs cy da el et eu fa fi fo ga gl gu he hr hu hy is ka kk km kn ku ky lo lt lv mk ml mn mr my ne nl no or pa pl ro si sk sl sq sr sv sw ta te tr uk ur uz zu".split(" ");
  const COUNTRY_CODES = "TW US JP KR VN ID TH PH MY IN GB FR DE ES IT CA AU NZ SG CN HK MO AF AX AL DZ AS AD AO AI AQ AG AR AM AW AT AZ BS BH BD BB BY BE BZ BJ BM BT BO BQ BA BW BV BR IO BN BG BF BI KH CM CV KY CF TD CL CX CC CO KM CG CD CK CR CI HR CU CW CY CZ DK DJ DM DO EC EG SV GQ ER EE SZ ET FK FO FJ FI GF PF TF GA GM GE GH GI GR GL GD GP GU GT GG GN GW GY HT HM VA HN HU IS IR IQ IE IM IL JM JE JO KZ KE KI KP KW KG LA LV LB LS LR LY LI LT LU MG MW MV ML MT MH MQ MR MU YT MX FM MD MC MN ME MS MA MZ MM NA NR NP NL NC NI NE NG NU NF MP NO OM PK PW PS PA PG PY PE PN PL PT PR QA RE RO RU RW BL SH KN LC MF PM VC WS SM ST SA SN RS SC SL SX SK SI SB SO ZA GS SS LK SD SR SJ SE CH SY TJ TZ TL TG TK TO TT TN TR TM TC TV UG UA AE UM UY UZ VU VE VG VI WF EH YE ZM ZW".split(" ");

  const languageOverrides = {
    zh: "中文／華語 (Mandarin Chinese)",
    en: "英文 (English)",
    ja: "日文 (Japanese)",
    ko: "韓文 (Korean)",
    vi: "越南文 (Vietnamese)",
  };
  const countryOverrides = {
    TW: "台灣 (Taiwan)",
    US: "美國 (United States)",
    GB: "英國 (United Kingdom)",
    KR: "韓國 (South Korea)",
    CN: "中國 (China)",
  };

  const makeDisplayList = (codes, type, overrides) => {
    const zhNames = new Intl.DisplayNames(["zh-TW"], { type });
    const enNames = new Intl.DisplayNames(["en"], { type });
    return codes
      .map((code) => {
        if (overrides[code]) return overrides[code];
        const zhName = zhNames.of(code);
        const enName = enNames.of(code);
        return zhName && enName ? `${zhName} (${enName})` : null;
      })
      .filter(Boolean)
      .filter((label, index, labels) => labels.indexOf(label) === index);
  };

  const lists = {
    language: makeDisplayList(LANGUAGE_CODES, "language", languageOverrides),
    region: makeDisplayList(COUNTRY_CODES, "region", countryOverrides),
  };

  document.querySelectorAll("select[data-profile-options]").forEach((select) => {
    const type = select.dataset.profileOptions;
    const placeholder = select.options[0]?.text || "請選擇 / Select";
    const previousValue = select.dataset.currentValue || select.value;
    select.replaceChildren(new Option(placeholder, ""));
    [...lists[type], "其他 (Other)"].forEach((label) => {
      select.add(new Option(label, label));
    });
    if (previousValue) select.value = previousValue;
  });
})();
