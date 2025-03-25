document.addEventListener("DOMContentLoaded", () => {
    fetch("/chart-data")
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error("Error loading chart data:", data.error);
                return;
            }

            // Extract data for the chart
            const labels = data.map(entry => entry.date);
            const previousTemps = data.map(entry => entry.previous_temp);
            const latestTemps = data.map(entry => entry.latest_temp);

            // Render the chart
            renderChart(labels, previousTemps, latestTemps);
        })
        .catch(error => console.error("Error fetching chart data:", error));
});

function renderChart(labels, previousTemps, latestTemps) {
    const ctx = document.getElementById("chart").getContext("2d");
    new Chart(ctx, {
        type: "line", // Change to "line" for better trend visualization
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Previous Temperatures",
                    data: previousTemps,
                    borderColor: "rgba(75, 192, 192, 1)",
                    backgroundColor: "rgba(75, 192, 192, 0.2)",
                    borderWidth: 1,
                    fill: true
                },
                {
                    label: "Latest Temperatures",
                    data: latestTemps,
                    borderColor: "rgba(255, 99, 132, 1)",
                    backgroundColor: "rgba(255, 99, 132, 0.2)",
                    borderWidth: 1,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: "top"
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}
