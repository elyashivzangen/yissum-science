# אפליקציית חישוב מס ל-IBKR בישראל

אפליקציה מקומית ב-Streamlit שמעלה דוח Activity Statement של Interactive Brokers ומפיקה חבילת עבודה לחישוב מס בישראל.

## יכולות

- קריאת CSV/Excel בפורמט דוח IBKR sectioned activity statement.
- זיהוי מכירות ממומשות לפי Trades -> ClosedLot.
- שליפת שער USD/ILS ממאגר הסדרות של בנק ישראל, סדרת RER_USD_ILS בעולם EXR.
- חישוב רווח/הפסד מוכר למס לפי שתי בדיקות: רווח נומינלי בש"ח ורווח דולרי מתורגם לפי שער מכירה.
- ברווח: לוקחת את הנמוך מבין שתי התוצאות החיוביות. בהפסד: מכירה בהפסד הנמוך יותר בערך מוחלט. בסימנים מנוגדים: 0.
- דיבידנדים מדווחים ברוטו ומס זר מוצג בנפרד.
- יצוא Excel מלא + נספח HTML בעברית + CSV-ים לחבילת עבודה.

## הרצה

```bash
cd apps/ibkr_tax_israel_app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

הפלט הוא נספח עבודה בלבד ואינו מחליף את טפסי רשות המסים הרשמיים כגון 1301, 1322/1325 ו-1324, לפי שנת המס.
