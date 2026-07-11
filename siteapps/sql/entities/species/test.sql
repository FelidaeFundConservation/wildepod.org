-- Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
--
-- This source code is licensed under the MIT license found in the
-- LICENSE file in the root directory of this source tree.




select count(*) from species_accepted(false)

select *
from species_accepted(false)
LIMIT 100

select count(*) from species_rejected(true)
