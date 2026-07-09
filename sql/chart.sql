select vs.nazwa , vs.kod_isin , vs.date , vs.close , vs.sma_50 , vs.sma_200 , vs.sma_50/vs.sma_200 sma_ratio from v_signals vs 
where vs.nazwa = 'KGHM'  and vs."date" > now() - INTERVAL '12 months'
order by vs."date" desc