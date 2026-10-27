# Units with spellings of their own

A reference file of the skill `support-a-decision-with-math`, for its steps 2 and 7: every number is text with its
unit, spelled as the design spells units. These kinds are spelled as follows. The rules are in `SKILL.md`.

- **Temperatures:** `"25 degC"`, `"77 degF"` or `"298.15 K"`. A change of temperature is `"5 delta_degC"`,
  `"5 delta_K"`, or a degree inside a compound unit (`"2.5 degC/W"`). A change converted to K comes back as
  `delta_K`, so it is never read as a temperature later: converting it to `degC` is refused; convert it to
  `delta_degC` instead. Never write a bare `C` or `F`: flo2-calc refuses them, because they could be coulombs or
  farads. Write `coulomb` or `farad` when you mean those.
- **Money:** the ISO 4217 code, `"987.50 USD"`. flo2-calc holds no exchange rates, so it refuses to add USD to
  EUR. To convert, give the rate as an input with its date and source,
  `{"id": "rate", "value": "0.92 EUR/USD", "source": "ECB reference rate, 2026-10-02"}`, and multiply by it.
- **Gallons:** `gal_us` or `gal_imp`. A bare `gal` is refused, because it is two different units.
- **Areas:** `acre` is the international acre (43,560 ft^2) and `ha` the hectare. A US survey acre is refused, because
  an area in "acres" does not say which acre it is: give an area your source states in survey measure in `ft^2` or
  `m^2`, as the source states it.
- **Heat:** `Btu` is the International Table Btu, and `Btu/h` a rate (`"18000 Btu/h"`, a U-factor
  `"0.056 Btu/(h*ft^2*delta_degF)"`). The ISO and thermochemical Btus are refused. `ton_refrigeration` is the
  refrigeration ton (12,000 Btu/h). A bare `ton` is refused: it is a mass in other systems, never a refrigeration ton.
- **Precious metals:** `ozt` (the troy ounce), `dwt` (the pennyweight) and `grain`. `oz` is the avoirdupois ounce,
  a different mass. A bare `gr` is refused, because it is written for both the grain and the gram.
- **Decibels:** a gain or loss is `"6 dB"` (`"0.2 dB/m"` per length); a power level is `"-30 dBm"` or `"10 dBW"`.
- **Prefixes:** units are case-sensitive, and a prefix's case is its size: `mJ` is a millijoule and `MJ` a
  megajoule.
- **A near-miss unit** may come back with what to write instead (`khz` gives `Write "kHz"`). When flo2-calc gives no
  hint, write the unit you mean yourself.
- **An unknown unit that pint reads** (`"mile"`) is named for what it is, with the units of that kind flo2-calc
  knows. Nothing is substituted: give the value in one of those units, from a source that states it, never a
  conversion factor you recall.
- **Shown simpler:** a computed value may come back in a simpler unit than it was computed in (`mAh/mA` shown as
  `h`); `simplified_from` says so. The value is the same. A whole number is written in full.
