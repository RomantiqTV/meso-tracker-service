# What this actually protects against, honestly

You asked for this to be "impenetrable." I can't build that, and no one selling desktop software can - this document says
plainly what the system does and doesn't stop, so you're deciding with real information instead of a sales pitch.

## The one fact that governs everything below

**Any check that runs on a PC you don't control can eventually be patched by whoever controls that PC.** A debugger
attached to the running process can see every value in memory and change what a jump instruction does, no matter how the
code on disk was obfuscated. This is true of every paid desktop app, every console game's DRM, and every always-online
"anti-cheat" - the difference between them is only how much time and skill it takes, not whether it's possible.

## What's actually in place, and what each layer is for

| Layer | Stops | Doesn't stop |
|---|---|---|
| Server-side subscription check on every launch (and every ~24h after) | Someone who cancels (or never paid) continuing to use a copy they already have, once their cached session expires | Someone who has also patched out the network call entirely |
| Hardware-ID binding, one device at a time | Casually sharing one paid account between friends on different PCs | A determined person running the app in a VM and resetting its disk/MachineGuid between uses (this gets expensive and inconvenient fast, which is the actual deterrent) |
| Nuitka compilation to native machine code (replaces the originally-planned PyArmor+PyInstaller combo - see `../MapleClassicBot/build/OBFUSCATION_STATUS.md`) | A curious user opening the .exe in a text editor or a basic decompiler and reading the source - there's no Python bytecode in the binary at all, only compiled machine code. Stronger than bytecode obfuscation (PyArmor-style), since there's nothing to decrypt back into readable code | A skilled reverse engineer with a disassembler/debugger and enough motivation - still possible in principle, just a much higher bar than reading bytecode. Plain string literals (e.g. URLs) are still visible via a tool like `strings`; no secrets are embedded client-side, so this is low-stakes here |
| License key stored only as a keyed hash (HMAC-SHA256 with a server-side pepper) | A stolen copy of the database being turned directly into working keys | Nothing protects a key once Stripe/your email has sent it to the real customer - that's expected; it's *their* key |
| Stripe webhook signature verification | Anyone forging a "payment succeeded" event against your server to get a free license | — (this one's solid: it's pure HMAC verification of something only Stripe's secret can produce) |
| HTTPS (Render terminates TLS automatically) | Network eavesdropping/tampering between the app and the server | — |

## What actually happens if someone cracks it

Realistically: a popular-enough paid tool eventually gets its license check patched out and shared. The goal of this
system isn't to make that impossible - it's to:
1. make casual sharing (just handing a friend your email+key) not work, since it's bound to one PC at a time,
2. make a cracked copy stop getting *updates*, which matters for something that reads a game's UI and breaks whenever
   the game patches,
3. make piracy require actual reverse-engineering skill, which keeps it well below "literally anyone can do it."

If you ever see your license key being shared, revoke it by clearing its `hwid` in the database (or add a `revoked_at`
timestamp - the column already exists) and the next phone-home fails for everyone using it.

## Data handled, and why it's low-risk if the database ever leaked

- No passwords exist in this system at all - login is email + a high-entropy generated key, not something a user chose
  (so there's no password-reuse risk to other accounts, and no weak-password risk).
- The database stores the key only as `HMAC-SHA256(pepper, key)`. Without the pepper (a separate env var, never in the
  database), the hash is useless; with the pepper, it still can't be reversed into the original key, only matched
  against guesses - and 128-bit random keys aren't guessable.
- No card numbers ever touch this server; Stripe holds all of that, and is a PCI Level 1 provider.

## If you want meaningfully more resistance later

- PyArmor's paid tiers add anti-debug tricks and "bind the build itself to your PyArmor account" features - a real but
  incremental improvement, not a different category.
- Rotating `JWT_SIGNING_SECRET` and `LICENSE_KEY_PEPPER` periodically invalidates any extracted secrets, at the cost of
  logging out every real customer too (they just re-enter their key, which still works).
- The biggest lever is usually non-technical: makes the product good enough, and updates it often enough, that paying
  is simply easier than keeping a cracked copy working.
