

(function ($) {
	/* "use strict" */

	var dzChartlist = function () {

		var screenWidth = $(window).width();
		let draw = Chart.controllers.line.__super__.draw; //draw shadow

		var chartBar = function () {
			var options = {
				series: [
					{
						name: 'Income',
						data: [96, 90],
						//radius: 12,	
					},
					{
						name: 'Income',
						data: [70, 80]
					},

				],
				chart: {
					type: 'bar',
					height: 150,

					toolbar: {
						show: false,
					},

				},
				plotOptions: {
					bar: {
						horizontal: false,
						columnWidth: '100%',
						endingShape: "rounded",
						borderRadius: 8,
					},

				},
				states: {
					hover: {
						filter: 'none',
					}
				},
				colors: ['#01BD9B', '#E6F9F5'],
				dataLabels: {
					enabled: true,
					offsetY: -25,
					formatter: function (val, opts) {
						return val + '%';
					},
					style: {
						fontSize: '12px',
						fontWeight: '500',
						colors: ['#000']
					},
				},
				markers: {
					shape: "circle",
				},


				legend: {
					show: false,
					fontSize: '12px',
					labels: {
						colors: '#000000',

					},
					markers: {
						width: 18,
						height: 18,
						strokeWidth: 10,
						strokeColor: '#fff',
						fillColors: undefined,
						radius: 12,
					}
				},
				stroke: {
					show: true,
					width: 10,
					curve: 'smooth',
					lineCap: 'round',
					colors: ['transparent']
				},
				grid: {
					show: true,
					strokeDashArray: 5,
					borderColor: 'rgba(0, 0, 0, 0.10)',
					xaxis: {
						lines: {
							show: false,
						}
					},
					yaxis: {
						lines: {
							show: true
						}
					},
				},
				xaxis: {
					categories: ['JAN', 'FEB', 'MAR', 'APR'],
					labels: {
						show: false,
						style: {
							colors: '#A5AAB4',
							fontSize: '12px',
							fontWeight: '400',
							fontFamily: 'poppins',
							cssClass: 'apexcharts-xaxis-label',
						},
					},
					crosshairs: {
						show: false,
					},
					axisBorder: {
						show: false,
					},
					axisTicks: {
						show: false,
					},
				},
				yaxis: {
					labels: {
						show: true,
						offsetX: -12,
						style: {
							colors: '#6F767E',
							fontSize: '12px',
							fontFamily: 'poppins',
							fontWeight: 400,
							cssClass: 'apexcharts-xaxis-label',
						},
					},

				},
			};

			var chartBar1 = new ApexCharts(document.querySelector("#chartBar"), options);
			chartBar1.render();
		}
		var pieChart1 = function () {
			var options = {
				series: [25, 33, 29, 16],
				chart: {
					type: 'donut',
					height: 180
				},
				dataLabels: {
					enabled: false
				},
				stroke: {
					width: 0,
				},
				colors: ['#B4EDFF', '#7BDFFF', '#FFFFFF', '#018DB9'],
				legend: {
					position: 'bottom',
					show: false
				},
				responsive: [{
					breakpoint: 1400,
					options: {
						chart: {
							height: 150
						},
					}
				}]
			};

			var chart = new ApexCharts(document.querySelector("#pieChart1"), options);
			chart.render();

		}
		var earningChart = function () {

			var chartWidth = $("#earningChart").width();
			/* console.log(chartWidth); */

			var options = {
				series: [
					{
						name: 'Net Profit',
						data: [667, 400, 380, 500, 600, 510, 610, 520, 400, 600, 510, 610, 610],
						/* radius: 30,	 */
					},
				],
				chart: {
					type: 'area',
					height: 250,
					width: chartWidth + 30,
					toolbar: {
						show: false,
					},
					offsetX: -20,
					zoom: {
						enabled: false
					},
					/* sparkline: {
						enabled: true
					} */

				},

				colors: ['#38BDE7'],
				dataLabels: {
					enabled: false,
				},

				legend: {
					show: false,
				},
				stroke: {
					show: true,
					width: 2,
					curve: 'smooth',
					colors: ['#38BDE7'],
				},
				grid: {
					show: true,
					borderColor: '#eee',
					xaxis: {
						lines: {
							show: false
						}
					},
					yaxis: {
						lines: {
							show: true
						}
					},
				},
				yaxis: {
					show: true,
					tickAmount: 6,
					min: 0,
					max: 800,
					labels: {
						offsetX: 0,
						colors: ['#6F767E'],
					}
				},
				xaxis: {
					categories: ['Jan', 'Feb', 'Mar', 'Apr', 'May ', 'Jun', 'Jul', 'Aug', 'Sep ', 'Oct', 'Nov', 'Dec'],
					overwriteCategories: undefined,
					axisBorder: {
						show: false,
					},
					axisTicks: {
						show: false
					},
					labels: {
						show: true,
						offsetX: 5,
						style: {
							fontSize: '12px',
							colors: ['#6F767E'],

						}
					},
				},
				fill: {
					opacity: 0.5,
					colors: '#38BDE7',
					type: 'gradient',
					gradient: {
						colorStops: [

							{
								offset: 0.6,
								color: '#38BDE7',
								opacity: .2
							},
							{
								offset: 0.6,
								color: '#38BDE7',
								opacity: .15
							},
							{
								offset: 100,
								color: 'white',
								opacity: 0
							}
						],

					}
				},
				tooltip: {
					enabled: true,
					style: {
						fontSize: '12px',
					},
					y: {
						formatter: function (val) {
							return "$" + val + "k"
						}
					}
				}
			};

			var chartBar1 = new ApexCharts(document.querySelector("#earningChart"), options);
			chartBar1.render();

			$(".earning-chart .nav-link").on('click', function () {
				var seriesType = $(this).attr('data-series');
				var columnData = [];
				switch (seriesType) {
					case "day":
						columnData = [700, 650, 680, 650, 700, 610, 710, 620];
						break;
					case "week":
						columnData = [700, 700, 680, 600, 700, 620, 710, 620];
						break;
					case "month":
						columnData = [700, 650, 690, 640, 700, 670, 710, 620];
						break;
					case "year":
						columnData = [700, 650, 590, 650, 700, 610, 710, 630];
						break;
					default:
						columnData = [700, 650, 680, 650, 700, 610, 710, 620];
				}
				chartBar1.updateSeries([
					{
						name: "Net Profit",
						data: columnData
					}
				]);
			})

		}
		var NewCustomers = function () {
			var options = {
				series: [
					{
						name: 'Net Profit',
						data: [100, 300, 200, 250, 200, 250, 200],
						/* radius: 30,	 */
					},
				],
				chart: {
					type: 'area',
					height: 70,
					//width: 400,
					toolbar: {
						show: false,
					},
					zoom: {
						enabled: false
					},
					sparkline: {
						enabled: true
					}

				},

				colors: ['#01BD9B'],
				dataLabels: {
					enabled: false,
				},

				legend: {
					show: false,
				},
				stroke: {
					show: true,
					width: 1,
					curve: 'smooth',
					colors: ['#01BD9B'],
				},

				grid: {
					show: false,
					borderColor: '#eee',
					padding: {
						top: 0,
						right: 0,
						bottom: 0,
						left: -1

					}
				},
				states: {
					normal: {
						filter: {
							type: 'none',
							value: 0
						}
					},
					hover: {
						filter: {
							type: 'none',
							value: 0
						}
					},
					active: {
						allowMultipleDataPointsSelection: false,
						filter: {
							type: 'none',
							value: 0
						}
					}
				},
				xaxis: {
					categories: ['Jan', 'feb', 'Mar', 'Apr', 'May', 'June', 'July'],
					axisBorder: {
						show: false,
					},
					axisTicks: {
						show: false
					},
					labels: {
						show: false,
						style: {
							fontSize: '12px',

						}
					},
					crosshairs: {
						show: false,
						position: 'front',
						stroke: {
							width: 1,
							dashArray: 3
						}
					},
					tooltip: {
						enabled: true,
						formatter: undefined,
						offsetY: 0,
						style: {
							fontSize: '12px',
						}
					}
				},
				yaxis: {
					show: false,
				},
				fill: {
					opacity: 0.9,
					colors: '#01BD9B',
					type: 'gradient',
					gradient: {
						colorStops: [

							{
								offset: 0,
								color: '#01BD9B',
								opacity: .4
							},
							{
								offset: 0.6,
								color: '#01BD9B',
								opacity: .4
							},
							{
								offset: 100,
								color: '#01BD9B',
								opacity: 0
							}
						],

					}
				},
				tooltip: {
					enabled: false,
					style: {
						fontSize: '12px',
					},
					y: {
						formatter: function (val) {
							return "$" + val + " thousands"
						}
					}
				}
			};

			var chartBar1 = new ApexCharts(document.querySelector("#NewCustomers"), options);
			chartBar1.render();

		}
		var donutChart1 = function () {
			$("span.donut1").peity("donut", {
				width: "5rem",
				height: "5rem"
			});
		}
		var NewExperience = function () {
			var options = {
				series: [
					{
						name: 'Net Profit',
						data: [100, 300, 200, 250, 200, 240, 180, 230, 200, 250, 300],
						/* radius: 30,	 */
					},
				],
				chart: {
					type: 'area',
					height: 42,
					width: 500,
					toolbar: {
						show: false,
					},
					zoom: {
						enabled: false
					},
					sparkline: {
						enabled: true
					}

				},

				colors: ['#E55555'],
				dataLabels: {
					enabled: false,
				},

				legend: {
					show: false,
				},
				stroke: {
					show: true,
					width: 1,
					curve: 'straight',
					colors: ['#E55555'],
				},

				grid: {
					show: false,
					borderColor: '#eee',
					padding: {
						top: 0,
						right: 0,
						bottom: 0,
						left: -1

					}
				},
				states: {
					normal: {
						filter: {
							type: 'none',
							value: 0
						}
					},
					hover: {
						filter: {
							type: 'none',
							value: 0
						}
					},
					active: {
						allowMultipleDataPointsSelection: false,
						filter: {
							type: 'none',
							value: 0
						}
					}
				},
				xaxis: {
					categories: ['Jan', 'feb', 'Mar', 'Apr', 'May', 'June', 'July', 'August', 'Sept', 'Oct'],
					axisBorder: {
						show: false,
					},
					axisTicks: {
						show: false
					},
					labels: {
						show: false,
						style: {
							fontSize: '12px',
						}
					},
					crosshairs: {
						show: false,
						position: 'front',
						stroke: {
							width: 1,
							dashArray: 3
						}
					},
					tooltip: {
						enabled: true,
						formatter: undefined,
						offsetY: 0,
						style: {
							fontSize: '12px',
						}
					}
				},
				yaxis: {
					show: false,
				},
				fill: {
					opacity: 0.9,
					colors: '#E55555',
					type: 'gradient',
					gradient: {
						colorStops: [

							{
								offset: 0,
								color: '#E55555',
								opacity: .5
							},
							{
								offset: 0.6,
								color: '#E55555',
								opacity: .5
							},
							{
								offset: 100,
								color: '#E55555',
								opacity: 0
							}
						],

					}
				},
				tooltip: {
					enabled: false,
					style: {
						fontSize: '12px',
					},
					y: {
						formatter: function (val) {
							return "$" + val + " thousands"
						}
					}
				}
			};

			var chartBar1 = new ApexCharts(document.querySelector("#NewExperience"), options);
			chartBar1.render();

		}
		var chartTimeline = function () {

			var optionsTimeline = {
				chart: {
					type: "bar",
					height: 250,
					stacked: true,
					toolbar: {
						show: false
					},
					sparkline: {
						//enabled: true
					},
					offsetX: -10,
				},
				series: [
					{
						name: "New Clients",
						data: [20, 40, 30, 50, 30, 20]
					}
				],

				plotOptions: {
					bar: {
						columnWidth: "28%",
						endingShape: "rounded",
						startingShape: "rounded",
						borderRadius: 5,

						/* colors: {
							backgroundBarColors: ['#111111', '#111111', '#111111', '#111111','#111111','#111111'],
							backgroundBarOpacity: 1,
							backgroundBarRadius: 5,
						}, */

					},
					distributed: true
				},

				colors: ['#216FED'],
				grid: {
					show: false,
				},
				legend: {
					show: false
				},
				fill: {
					type: 'gradient',
					gradient: {
						shade: 'dark',
						type: 'vertical',
						shadeIntensity: 0.5,
						//gradientToColors: ['#FFEABA'],
						//inverseColors: true,
						//opacityFrom: 1,
						//opacityTo: 0,
						//stops: [0, 100]
						colorStops: [


							{
								offset: 0,
								color: '#FFEABA',
								opacity: 1
							},
							{
								offset: 100,
								color: '#111111',
								opacity: 1
							}



						]
					}
				},
				dataLabels: {
					enabled: false,
					colors: ['#000'],
					dropShadow: {
						enabled: true,
						top: 1,
						left: 1,
						blur: 1,
						opacity: 1
					}
				},
				stroke: {
					show: true,
					lineCap: 'rounded',
				},
				xaxis: {
					categories: ['06', '07', '08', '09', '10', '11'],
					labels: {
						show: false,
						style: {
							colors: '#FFEABA',
							fontSize: '13px',
							fontFamily: 'poppins',
							fontWeight: 100,
							cssClass: 'apexcharts-xaxis-label',
						},
					},
					crosshairs: {
						show: false,
					},
					axisBorder: {
						show: false,
					},
					axisTicks: {
						show: false,
					},

				},
				yaxis: {
					opposite: true,
					labels: {
						style: {
							colors: '#808080',
							fontSize: '14px',
							fontFamily: 'Poppins',
							fontWeight: 100,

						},
						offsetX: -15,
						formatter: function (y) {
							return y.toFixed() + "k";
						}
					},
				},
				tooltip: {
					x: {
						show: true
					}
				},
				responsive: [{
					breakpoint: 375,
					options: {
						xaxis: {
							categories: ['06', '07', '08', '09', '10', '11'],
						},
						chart: {
							height: 250,
						},
						series: [
							{
								name: "New Clients",
								data: [300, 250, 600, 600, 400, 450],
							}
						],

					}
				},
				{
					breakpoint: 575,
					options: {
						chart: {
							height: 250,
						},
						series: [
							{
								name: "New Clients",
								data: [300, 250, 600, 600, 400, 450, 310, 470, 480],
							}
						],
						xaxis: {
							categories: ['06', '07', '08', '09', '10', '11', '12', '13', '14'],
						}
					}
				}

				]
			};
			var chartTimelineRender = new ApexCharts(document.querySelector("#chartTimeline"), optionsTimeline);
			chartTimelineRender.render();
		}





		/* Function ============ */
		return {
			init: function () {
			},


			load: function () {
				chartBar();
				pieChart1();
				earningChart();
				NewCustomers();
				donutChart1();
				NewExperience();
				chartTimeline();


			},

			resize: function () {
				earningChart();
			}
		}

	}();



	jQuery(window).on('load', function () {
		setTimeout(function () {
			dzChartlist.load();
		}, 1000);

	});



})(jQuery);
