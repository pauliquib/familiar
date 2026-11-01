# Generátor zvuků upozornění: krátké pixelové zvuky syntetizované kódem (familiar/upozorneni.py).
#
#   python3 -I tools/zvuky.py [cílový adresář]      (výchozí familiar/zvuky)
#
# Sady: „pipani“ (8-bit čtverec se střídou 25 %, jako staré konzole) a „jemne“ (sinus
# s alikvótou a zvonovým doznivem). Každá sada má zvuk pro každý druh upozornění;
# WAV 16 bit mono 22 050 Hz, nejvýš 0,6 s. Bez náhody: stejný kód = stejné soubory.
# Vlastní dílo projektu, CC0 1.0.
import argparse, io, math, os, struct, sys, wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATE = 22050
PEAK = 0.45             # rezerva proti zkreslení a hlasitosti
ATTACK_S = 0.004
DRUHY = ("dokonceno", "povoleni", "otazka", "chyba", "compact")

# nota → kmitočet (rovnoměrné ladění, A4 = 440 Hz)
_N = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}


def hz(nota):
    """'C6', 'Eb4', 'F#5' → Hz."""
    k, rest = _N[nota[0]], nota[1:]
    if rest[0] in "b#":
        k += -1 if rest[0] == "b" else 1
        rest = rest[1:]
    return 440.0 * 2 ** ((k + 12 * (int(rest) - 4)) / 12)


def _square(phase, duty=0.25):
    return 1.0 if phase % 1.0 < duty else -1.0


def _bell(phase):
    return 0.8 * math.sin(2 * math.pi * phase) + 0.2 * math.sin(4 * math.pi * phase)


def tone(f0, dur, wave_fn, f1=None, decay=None, gain=1.0):
    """Jeden tón: kmitočet f0 (s f1 klouže lineárně k f1), náběh ATTACK_S, rovná hladina
    nebo exponenciální doznívání (decay = časová konstanta, s) a krátký konec. Fáze se
    sčítá, takže klouzání nepraská."""
    n = int(dur * RATE)
    out, phase = [], 0.0
    for i in range(n):
        t = i / RATE
        f = f0 if f1 is None else f0 + (f1 - f0) * i / n
        phase += f / RATE
        env = min(1.0, t / ATTACK_S)
        if decay:
            env *= math.exp(-t / decay)
        env *= min(1.0, (n - i) / (0.006 * RATE))         # 6 ms dolů, ať konec necvakne
        out.append(gain * env * wave_fn(phase))
    return out


def ticho(dur):
    return [0.0] * int(dur * RATE)


def _sq(duty):
    return lambda p: _square(p, duty)


def pipani():
    sq, half = _sq(0.25), _sq(0.5)
    return {
        # vzestupné arpeggio C dur
        "dokonceno": sum((tone(hz(n), 0.055, sq) for n in ("C6", "E6", "G6")), []) + tone(hz("C7"), 0.16, sq),
        # dvakrát dvojtón „pozor“
        "povoleni": (tone(hz("A5"), 0.07, sq) + tone(hz("E6"), 0.07, sq) + ticho(0.06)
                     + tone(hz("A5"), 0.07, sq) + tone(hz("E6"), 0.11, sq)),
        # klouzání nahoru a tečka – otazník
        "otazka": tone(hz("E5"), 0.16, sq, f1=hz("B5")) + ticho(0.04) + tone(hz("E6"), 0.07, sq),
        # sestupná zlá trojice, plný čtverec zní tvrdě
        "chyba": tone(hz("G4"), 0.1, half) + tone(hz("Eb4"), 0.1, half) + tone(hz("C4"), 0.22, half, decay=0.12),
        # hvizd dolů – zhuštění kontextu
        "compact": tone(1600, 0.24, _sq(0.125), f1=300, gain=0.8),
    }


def jemne():
    b = _bell
    return {
        "dokonceno": tone(hz("G5"), 0.11, b, decay=0.08) + tone(hz("C6"), 0.4, b, decay=0.14),
        "povoleni": tone(hz("B5"), 0.16, b, decay=0.07) + tone(hz("B5"), 0.36, b, decay=0.12),
        "otazka": tone(hz("E5"), 0.13, b, decay=0.08) + tone(hz("A5"), 0.34, b, decay=0.12),
        "chyba": tone(hz("A4"), 0.16, b, decay=0.1) + tone(hz("F4"), 0.42, b, decay=0.15),
        "compact": sum((tone(hz(n), 0.11, b, decay=0.05) for n in ("A5", "E5")), []) + tone(hz("C5"), 0.25, b, decay=0.08),
    }


SADY = {"pipani": pipani, "jemne": jemne}


def wav_bytes(samples):
    """Vzorky −1..1 → obsah WAV (16 bit mono RATE) s normalizací na PEAK."""
    top = max((abs(s) for s in samples), default=0.0) or 1.0
    frames = struct.pack(f"<{len(samples)}h", *(round(s / top * PEAK * 32767) for s in samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    return buf.getvalue()


CREDITS = """Zvuky upozornění – Pixel Familiars

Vlastní dílo projektu Pixel Familiars, syntetizované kódem (tools/zvuky.py).
Licence: Creative Commons Zero v1.0 Universal (CC0 1.0), public domain
         https://creativecommons.org/publicdomain/zero/1.0/

Sady: pipani (8-bit čtverec), jemne (zvonky). Znovu vygeneruje: python3 -I tools/zvuky.py
"""


def export(dest):
    for sada, fn in SADY.items():
        os.makedirs(os.path.join(dest, sada), exist_ok=True)
        zvuky = fn()
        assert set(zvuky) == set(DRUHY), sada
        for druh, samples in zvuky.items():
            with open(os.path.join(dest, sada, f"{druh}.wav"), "wb") as f:
                f.write(wav_bytes(samples))
    with open(os.path.join(dest, "CREDITS.txt"), "w", encoding="utf-8") as f:
        f.write(CREDITS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="zvuky upozornění syntetizované kódem")
    ap.add_argument("dest", nargs="?", default=os.path.join(REPO, "familiar", "zvuky"))
    args = ap.parse_args(argv)
    export(args.dest)
    print(f"zvuky zapsány do {args.dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
