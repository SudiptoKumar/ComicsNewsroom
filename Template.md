# ComicsNewsroom Telegram Dynamic Template System

Channel: **@ComicsNewsroom**

The post renderer is dynamic. Do not force every story into one layout.

## Global design principles

```text
ONE STORY
    ↓
ONE CLEAR HOOK
    ↓
ONE STRONG TITLE
    ↓
2–4 HIGH-VALUE FACTS
    ↓
OPTIONAL WHY-FANS-CARE
    ↓
OPTIONAL DIRECT VIDEO
    ↓
SOURCE
```

The reader should understand the important development quickly. Routine background is omitted.

## Template 1: Major / Breaking

```text
[PHOTO]

🚨 BREAKING

[WORK / FRANCHISE]

[One concise factual sentence]

✦ [Important fact]
✦ [Important fact]
✦ [What's next]

💡 Why fans care: [only when genuinely useful]

@ComicsNewsroom #...

Source: [clickable publication]
```

## Template 2: Trailer / PV

```text
[TRAILER THUMBNAIL]

🎞️ NEW TRAILER

[WORK TITLE]

[What was released]

✦ [Studio / production detail]
✦ [Release information]
✦ [Important reveal]

🎥 WATCH OFFICIAL TRAILER · [YouTube / Crunchyroll]

@ComicsNewsroom #Anime #Trailer

Source: [clickable publication]
```

The direct video link is inserted only after URL discovery and verification.

## Template 3: New Season / Sequel

```text
[PHOTO]

🔄 NEW SEASON

[WORK TITLE]

[Season continuation announcement]

✦ [Official confirmation]
✦ [Studio / staff]
✦ [Release timing]

@ComicsNewsroom #Anime #NewSeason

Source: [clickable publication]
```

## Template 4: Manga → Anime

```text
[KEY VISUAL]

⚡ MANGA → ANIME

[WORK TITLE]

[Adaptation announcement]

✦ Studio: ...
✦ Format: ...
✦ Release: ...

@ComicsNewsroom #Manga #Anime

Source: [clickable publication]
```

## Template 5: Major Manga Update

```text
[MANGA ART]

📖 MANGA UPDATE

[WORK TITLE]

[What changed]

✦ Status: ...
✦ Next update: ...
✦ Important detail: ...

@ComicsNewsroom #Manga #MangaUpdate

Source: [clickable publication]
```

## Template 6: Manga Finale / Ending

```text
[MANGA ART]

📖 MANGA FINALE

[WORK TITLE]

[Ending announcement]

✦ Final chapter: ...
✦ Publication status: ...

@ComicsNewsroom #Manga #FinalChapter

Source: [clickable publication]
```

## Template 7: Marvel

```text
[COMIC ART]

◆ MARVEL COMICS

[WORK / CHARACTER / EVENT]

[Major development]

✦ [Writer / artist / release]
✦ [Storyline / event detail]
✦ [Important next step]

@ComicsNewsroom #Marvel #Comics

Source: [clickable publication]
```

## Template 8: DC

```text
[COMIC ART]

◆ DC COMICS

[WORK / CHARACTER / EVENT]

[Major development]

✦ [Creator / release]
✦ [Storyline / event detail]
✦ [Important next step]

@ComicsNewsroom #DC #Comics

Source: [clickable publication]
```

## Template 9: Major Comic Event / Storyline

```text
[COMIC ART]

◆ MAJOR COMIC EVENT

[WORK / EVENT]

[Concise explanation]

✦ [What changed]
✦ [Who is involved]
✦ [Release / next step]

@ComicsNewsroom #Comics #Event

Source: [clickable publication]
```

## Template 10: Comic Adaptation

```text
[ART / FIRST LOOK]

🎬 COMIC ADAPTATION

[WORK TITLE]

[Adaptation announcement]

✦ Format: ...
✦ Studio / platform: ...
✦ Release: ...

@ComicsNewsroom #Comics #Adaptation

Source: [clickable publication]
```

## Rendering rules

- Rich HTML is generated deterministically by Python.
- The model never emits HTML or Markdown.
- `✦` is the detail marker.
- The source publication name is clickable.
- No raw URLs are displayed.
- Direct video links are clickable and appear only when verified.
- The channel tag is `@ComicsNewsroom`.
- Hashtags are limited to a small relevant set.
- Empty or unsupported fields are removed.
- Posters and comic covers preserve their original aspect ratio.
