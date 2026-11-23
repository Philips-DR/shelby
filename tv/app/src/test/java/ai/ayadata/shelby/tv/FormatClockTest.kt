package ai.ayadata.shelby.tv

import org.junit.Assert.assertEquals
import org.junit.Test

class FormatClockTest {
    @Test fun `under an hour is minutes and seconds`() {
        assertEquals("0:00", formatClock(0.0))
        assertEquals("0:57", formatClock(57.387))
        assertEquals("3:07", formatClock(187.0))
        assertEquals("19:39", formatClock(1179.9))
    }

    @Test fun `an hour or more shows hours`() {
        assertEquals("1:23:44", formatClock(5024.7))
        assertEquals("2:06:33", formatClock(7593.7))
        assertEquals("6:39:45", formatClock(23985.073))
    }

    @Test fun `it rounds down, as a clock does`() {
        assertEquals("0:59", formatClock(59.99))
        assertEquals("1:00", formatClock(60.0))
    }

    @Test fun `a negative time shows zero`() {
        assertEquals("0:00", formatClock(-5.0))
    }
}
