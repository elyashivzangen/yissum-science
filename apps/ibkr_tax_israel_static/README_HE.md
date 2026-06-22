# גרסת GitHub Pages - IBKR Israel Tax Workpaper

זוהי גרסה סטטית של האפליקציה, שמיועדת לרוץ ישירות דרך GitHub Pages בלי שרת Python, בלי Streamlit Cloud ובלי התקנה על המחשב.

## מה זה נותן

- URL קבוע תחת GitHub Pages.
- אפשר לפתוח גם מהמחשב וגם מהטלפון.
- העלאת CSV של IBKR וחישוב בדפדפן.
- אין backend: הקובץ לא נשלח לשרת האפליקציה.
- הורדת נספח HTML להדפסה ל-PDF, CSV פירוט מכירות, CSV שערי מטח ו-CSV סיכום.

## מגבלות לעומת גרסת Streamlit

- תומך בעיקר ב-CSV של IBKR. לא XLSX, כי GitHub Pages הוא אתר סטטי ללא Python.
- ZIP/XLSX מלאים דורשים ספריות JavaScript נוספות או שרת backend. כדי לשמור את הגרסה עצמאית וללא מקור חיצוני, הפלט הוא HTML/CSV.
- שליפת שערי בנק ישראל מתבצעת מהדפדפן. אם הדפדפן חוסם CORS, אפשר להזין שערים ידנית דרך קישורי BOI שמופיעים בטבלה.

## הפעלה

לאחר מיזוג ה-PR ל-main:

1. ב-GitHub להיכנס ל-Settings > Pages.
2. לבחור Source: GitHub Actions.
3. להריץ את workflow בשם `Deploy IBKR Tax Static App to GitHub Pages`, או לבצע push ל-main.
4. לפתוח את כתובת ה-Pages שתופיע ב-workflow.

כתובת צפויה לאחר פריסה:

```text
https://elyashivzangen.github.io/yissum-science/
```

אם רוצים שהאפליקציה תהיה בתת-נתיב ייעודי, אפשר בהמשך להעביר אותה לריפו נפרד או להוסיף דף ניווט.
